(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  // ── DOM refs ─────────────────────────────────────────────────────────────
  const tenantInput = $("tenant");
  const topkInput = $("topk");
  const queryInput = $("q");
  const sendBtn = $("send");
  const clearBtn = $("clear");
  const statusEl = $("status");
  const eventsEl = $("events");
  const answerPanel = $("answer-panel");
  const answerEl = $("answer");
  const srcCountEl = $("src-count");
  const sourcesEl = $("sources");
  const rawEl = $("raw");

  // ── helpers ──────────────────────────────────────────────────────────────
  const setStatus = (label, cls) => {
    statusEl.textContent = label;
    statusEl.className = `status ${cls}`;
  };

  const t0Ref = { value: 0 };
  const fmtMsSince = (tsMs) => {
    if (!t0Ref.value) return "";
    const delta = tsMs - t0Ref.value;
    return delta >= 0 ? `+${delta}ms` : `${delta}ms`;
  };

  const truncate = (str, n = 200) =>
    typeof str === "string" && str.length > n ? str.slice(0, n) + "…" : str;

  const escapeHtml = (s) =>
    String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

  // ── event renderers (one per event type) ──────────────────────────────────
  const renderers = {
    "planner.plan": (d) => {
      const steps = (d.plan && d.plan.steps) || [];
      const stepsHtml = steps
        .map(
          (s) =>
            `<code>${escapeHtml(s.name)}</code> args=<code>${escapeHtml(
              JSON.stringify(s.arguments)
            )}</code>`
        )
        .join("<br>");
      const rationale = d.plan && d.plan.rationale ? `<br><em>${escapeHtml(d.plan.rationale)}</em>` : "";
      return `${steps.length} step(s):<br>${stepsHtml}${rationale}`;
    },
    "tool.span.start": (d) =>
      `span=<code>${d.span_id}</code> tool=<code>${d.name}</code> args=<code>${escapeHtml(
        JSON.stringify(d.args)
      )}</code>`,
    "tool.span.end": (d) =>
      `span=<code>${d.span_id}</code> latency=<code>${d.latency_ms}ms</code> chunks=<code>${d.chunk_count}</code> err=<code>${d.is_error}</code><details><summary>preview</summary><pre>${escapeHtml(
        truncate(d.content_preview, 400)
      )}</pre></details>`,
    "tool.span.error": (d) =>
      `span=<code>${d.span_id}</code> error=<code>${escapeHtml(d.error_type || "")}</code> msg=<code>${escapeHtml(
        truncate(d.error_message || "", 200)
      )}</code>`,
    "executor.parallel": (d) =>
      `fan_out=<code>${d.fan_out}</code> group_latency=<code>${d.group_latency_ms}ms</code>`,
    "verifier.start": (d) =>
      `peer_count=<code>${d.peer_count}</code> model=<code>${d.model}</code>`,
    "verifier.disagreement": (d) => {
      const ids = (d.evidence_chunk_ids || []).map((x) => `<code>${escapeHtml(x).slice(0, 14)}…</code>`).join(", ");
      return `reason=<code>${escapeHtml(d.reason)}</code> peer_count=<code>${d.peer_count}</code>${
        d.error_type ? ` error=<code>${escapeHtml(d.error_type)}</code>` : ""
      }<br><em>${escapeHtml(truncate(d.summary, 300))}</em>${ids ? `<br>evidence: ${ids}` : ""}`;
    },
    "verifier.complete": (d) =>
      `verdict=<code>${escapeHtml(d.verdict)}</code> evidence_count=<code>${d.evidence_chunk_count}</code> latency=<code>${d.latency_ms}ms</code>`,
    "synthesizer.final": (d) =>
      `sources=<code>${d.sources_count}</code> answer=<code>${escapeHtml(truncate(d.answer, 80))}</code>`,
    error: (d) => `<strong style="color:var(--error)">${escapeHtml(d.message || "unknown error")}</strong>`,
  };

  const eventTypeClass = (type) => "event_" ? type.replace(/\./g, "_") : "";

  const renderEvent = (eventType, data) => {
    const t0 = t0Ref.value || data.ts_ms;
    if (!t0Ref.value) t0Ref.value = data.ts_ms;
    const meta = data.ts_ms ? fmtMsSince(data.ts_ms) : "";
    const cls = (eventType || "error").replace(/\./g, "_");
    const renderer = renderers[eventType] || ((d) => `<pre>${escapeHtml(JSON.stringify(d))}</pre>`);
    const body = renderer(data);

    const div = document.createElement("div");
    div.className = `event ${cls}`;
    div.innerHTML = `
      <div class="event-header">
        <span class="event-type">${escapeHtml(eventType)}</span>
        <span class="event-meta">seq=${data.seq ?? "—"} ${meta}</span>
      </div>
      <div class="event-body">${body}</div>`;
    eventsEl.appendChild(div);
    eventsEl.scrollTop = eventsEl.scrollHeight;

    // Capture final answer + sources
    if (eventType === "synthesizer.final") {
      answerEl.textContent = data.answer || "(no answer)";
      srcCountEl.textContent = data.sources_count ?? 0;
      answerPanel.classList.remove("hidden");
    }
  };

  // ── parse SSE frames from a streaming fetch body ──────────────────────────
  // Frames separated by `\n\n`; each has `event: <type>\ndata: <json>` lines.
  const parseSSEChunk = (buffer) => {
    const frames = [];
    let idx;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      let eventType = "message";
      let dataStr = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) eventType = line.slice(7).trim();
        else if (line.startsWith("data: ")) dataStr += line.slice(6);
      }
      if (dataStr) {
        try {
          frames.push({ eventType, data: JSON.parse(dataStr) });
        } catch (e) {
          frames.push({ eventType: "error", data: { message: `Parse error: ${e.message}` } });
        }
      }
    }
    return { frames, buffer };
  };

  // ── main runner ──────────────────────────────────────────────────────────
  const run = async () => {
    const query = queryInput.value.trim();
    if (!query) {
      setStatus("empty query", "error");
      return;
    }
    const mode = document.querySelector('input[name="mode"]:checked').value;
    const tenant = tenantInput.value.trim();
    const topk = parseInt(topkInput.value, 10) || 6;

    // Build request
    const body = { query, tenant_id: tenant, top_k: topk };
    if (mode === "agent") body.agent_mode = true;
    if (mode === "swarm") body.swarm_mode = true;
    if (mode === "debate") {
      body.swarm_mode = true;
      body.debate = true;
    }

    // Reset UI
    eventsEl.innerHTML = "";
    answerEl.textContent = "";
    sourcesEl.innerHTML = "";
    rawEl.textContent = "";
    answerPanel.classList.add("hidden");
    t0Ref.value = 0;
    sendBtn.disabled = true;
    setStatus(`running (${mode})…`, "running");

    const url = mode === "basic" ? "/api/v1/query" : "/api/v1/agent/v1/run/stream";

    try {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (mode === "basic") {
        const j = await resp.json();
        rawEl.textContent = JSON.stringify(j, null, 2);
        const data = (j && (j.data || j)) || {};
        answerEl.textContent = data.answer || "(no answer)";
        srcCountEl.textContent = (data.sources && data.sources.length) || 0;
        if (data.sources && data.sources.length) {
          for (const src of data.sources) {
            const el = document.createElement("div");
            el.className = "source-item";
            const meta = src.metadata || {};
            el.textContent = `${meta.title || meta.source || "?"} | page=${meta.page_number ?? "?"} score=${(src.score ?? 0).toFixed(3)}`;
            sourcesEl.appendChild(el);
          }
        }
        answerPanel.classList.remove("hidden");
        setStatus(`done · ${data.latency_ms || 0}ms`, "done");
      } else {
        // SSE streaming via fetch + ReadableStream
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        let raw = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          raw += chunk;
          buf += chunk;
          const { frames, buffer: rest } = parseSSEChunk(buf);
          buf = rest;
          for (const { eventType, data } of frames) renderEvent(eventType, data);
        }
        rawEl.textContent = raw;
        setStatus("done", "done");
      }
    } catch (e) {
      console.error(e);
      setStatus(`error: ${e.message}`, "error");
      renderEvent("error", { message: e.message });
    } finally {
      sendBtn.disabled = false;
    }
  };

  // ── wiring ───────────────────────────────────────────────────────────────
  sendBtn.addEventListener("click", run);
  clearBtn.addEventListener("click", () => {
    eventsEl.innerHTML = "";
    answerEl.textContent = "";
    sourcesEl.innerHTML = "";
    rawEl.textContent = "";
    answerPanel.classList.add("hidden");
    setStatus("idle", "idle");
  });
  queryInput.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") run();
  });
})();
