(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  // ── DOM refs ─────────────────────────────────────────────────────────────
  const tenantInput = $("tenant");
  const sessionInput = $("session");
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
  const fbUpBtn = $("fb-up");
  const fbDownBtn = $("fb-down");
  const fbComment = $("fb-comment");
  const fbStatus = $("fb-status");
  const fbStats = $("fb-stats");
  const ingDocInput = $("ing-doc");
const ingFileInput = $("ing-file");
  const ingTenantInput = $("ing-tenant");
  const ingContentInput = $("ing-content");
  const ingForceInput = $("ing-force");
  const ingSubmitBtn = $("ing-submit");
  const ingStatusEl = $("ing-status");
  const ingProgressEl = $("ing-progress");

  const newSessionId = () =>
    (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "") : Math.random().toString(16).slice(2)).slice(0, 16);
  sessionInput.value = newSessionId();

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

    // Build request — rotate session_id per run so feedback binds to this answer
    sessionInput.value = newSessionId();
    const session = sessionInput.value;
    const body = { query, tenant_id: tenant, top_k: topk, session_id: session };
    if (mode === "agent") body.agent_mode = true;
    if (mode === "swarm") body.swarm_mode = true;
    if (mode === "debate") {
      body.swarm_mode = true;
      body.debate = true;
    }
    fbStatus.textContent = "";
    fbUpBtn.disabled = false;
    fbDownBtn.disabled = false;

    // Reset UI
    eventsEl.innerHTML = "";
    answerEl.textContent = "";
    sourcesEl.innerHTML = "";
    rawEl.textContent = "";
    answerPanel.classList.add("hidden");
    t0Ref.value = 0;
    sendBtn.disabled = true;
    setStatus(`running (${mode})…`, "running");

    // 统一走 /query 同步端点：三向路由 swarm_mode > agent_mode > QueryPipeline。
    // 全功能（A/B + Cache + Faithfulness + Audit + _store_last_qa）由后端 .run() 完成。
    body.include_images = true;
    const url = "/api/v1/query";
    const t0 = Date.now();

    // 显示答案面板 + 等待占位符；启动 elapsed 计时器
    answerPanel.classList.remove("hidden");
    answerEl.textContent = `⏳ 等待回答…(模式=${mode}，30-120 秒)`;
    const elapsedTimer = setInterval(() => {
      const sec = ((Date.now() - t0) / 1000).toFixed(1);
      setStatus(`running (${mode})… ${sec}s`, "running");
    }, 200);

    try {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      clearInterval(elapsedTimer);

      if (!resp.ok) {
        let detail = "";
        try { detail = JSON.stringify(await resp.json()); } catch (_) { detail = await resp.text(); }
        throw new Error(`HTTP ${resp.status} ${detail}`);
      }
      const env = await resp.json();
      if (!env.success) throw new Error(env.error || "query failed");
      const data = env.data || {};
      rawEl.textContent = JSON.stringify(env, null, 2);

      // 渲染答案
      answerEl.textContent = data.answer || "(empty answer)";

      // 渲染来源
      const sources = data.sources || [];
      srcCountEl.textContent = sources.length;
      if (!sources.length) {
        sourcesEl.innerHTML = "<em>(no sources)</em>";
      } else {
        sourcesEl.innerHTML = sources.map((s, i) => {
          const m = s.metadata || {};
          const score = s.final_score ?? s.rerank_score ?? s.rrf_score ?? s.dense_score ?? 0;
          const ctype = m.chunk_type || "?";
          const loc = ctype === "web"
            ? `URL=${escapeHtml((m.source || "").slice(0, 80))}`
            : `页=${m.page_number ?? "?"}`;
          const img = m.image_b64 ? `<br><img style="max-width:200px;margin-top:4px;" src="data:image/png;base64,${m.image_b64}">` : "";
          return `<div class="source"><div class="source-meta">来源${i+1} · ${escapeHtml(loc)} · 类型=${escapeHtml(ctype)} · score=${Number(score).toFixed(3)}</div><div>${escapeHtml(String(s.content || ""))}</div>${img}</div>`;
        }).join("");
      }

      // 渲染元信息到 Event Timeline（虽然非流式无事件，把后端 trace + faithfulness 当 1 个 event 显示）
      eventsEl.innerHTML = "";
      renderEvent("query.complete", {
        ts_ms: Date.now(),
        trace_id: env.trace_id || data.trace_id || "—",
        latency_ms: data.latency_ms || (Date.now() - t0),
        faithfulness: data.faithfulness_score ?? "—",
        model: data.model || "—",
        sources_count: sources.length,
        answer: data.answer || "",
      });

      setStatus(`done · ${Date.now() - t0}ms`, "done");
    } catch (e) {
      clearInterval(elapsedTimer);
      console.error(e);
      setStatus(`error: ${e.message}`, "error");
      renderEvent("error", { message: e.message });
    } finally {
      sendBtn.disabled = false;
    }
  };

  // ── feedback ─────────────────────────────────────────────────────────────
  const refreshFeedbackStats = async () => {
    try {
      const r = await fetch("/api/v1/feedback/stats");
      const j = await r.json();
      const d = (j && (j.data || j)) || {};
      const total = d.total ?? 0;
      const pos = d.positive ?? 0;
      const neg = d.negative ?? 0;
      const pct = total > 0 ? ((pos / total) * 100).toFixed(1) : "0.0";
      fbStats.textContent = `stats: total=${total} 👍${pos} 👎${neg} (${pct}% positive)`;
    } catch (e) {
      fbStats.textContent = `stats: error ${e.message}`;
    }
  };

  const submitFeedback = async (value) => {
    const body = {
      session_id: sessionInput.value,
      feedback: value,
      comment: fbComment.value.trim(),
      tenant_id: tenantInput.value.trim(),
    };
    fbStatus.textContent = "sending…";
    fbUpBtn.disabled = true;
    fbDownBtn.disabled = true;
    try {
      const r = await fetch("/api/v1/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      fbStatus.textContent = `✓ recorded (${value > 0 ? "👍" : "👎"})`;
      await refreshFeedbackStats();
    } catch (e) {
      fbStatus.textContent = `error: ${e.message}`;
      fbUpBtn.disabled = false;
      fbDownBtn.disabled = false;
    }
  };

  fbUpBtn.addEventListener("click", () => submitFeedback(1));
  fbDownBtn.addEventListener("click", () => submitFeedback(-1));
  refreshFeedbackStats();

  // ── ingest ───────────────────────────────────────────────────────────────
  const setIngStatus = (label, cls) => {
    ingStatusEl.textContent = label;
    ingStatusEl.className = `status ${cls}`;
  };

  const pollIngestStatus = async (taskId) => {
    const url = `/api/v1/ingest/status/${encodeURIComponent(taskId)}`;
    const started = Date.now();
    for (let i = 0; i < 60; i++) {
      try {
        const r = await fetch(url);
        const j = await r.json();
        const d = (j && (j.data || j)) || {};
        const elapsed = ((Date.now() - started) / 1000).toFixed(1);
        ingProgressEl.innerHTML = `<code>task=${escapeHtml(taskId)}</code> status=<code>${escapeHtml(d.status || "?")}</code> elapsed=<code>${elapsed}s</code>${
          d.result ? `<pre>${escapeHtml(JSON.stringify(d.result, null, 2))}</pre>` : ""
        }`;
        if (d.status && ["complete", "success", "failed", "error"].includes(String(d.status).toLowerCase())) {
          setIngStatus(`done (${d.status})`, d.success === false ? "error" : "done");
          return;
        }
      } catch (e) {
        ingProgressEl.innerHTML = `<strong style="color:var(--error)">poll error: ${escapeHtml(e.message)}</strong>`;
        setIngStatus("error", "error");
        return;
      }
      await new Promise((res) => setTimeout(res, 2000));
    }
    setIngStatus("poll timeout", "error");
  };

  const submitIngest = async () => {
    const docId = ingDocInput.value.trim();
    const content = ingContentInput.value;
    const file = ingFileInput && ingFileInput.files && ingFileInput.files[0];
    const tenant = ingTenantInput.value.trim();
    const force = ingForceInput.checked;

    if (!file && !content) {
      setIngStatus("file or content required", "error");
      return;
    }

    ingSubmitBtn.disabled = true;
    ingProgressEl.innerHTML = "";

    try {
      if (file) {
        setIngStatus(`uploading ${file.name} (${(file.size / 1024).toFixed(1)}KB)…`, "running");
        const fd = new FormData();
        fd.append("file", file);
        const params = new URLSearchParams();
        if (docId) params.set("doc_id", docId);
        if (tenant) params.set("tenant_id", tenant);
        if (force) params.set("force", "true");
        const r = await fetch(`/api/v1/ingest/upload?${params.toString()}`, {
          method: "POST",
          body: fd,
        });
        const j = await r.json();
        if (!r.ok) throw new Error(j.detail || j.error || `HTTP ${r.status}`);
        const d = j.data || {};
        setIngStatus(j.success ? "done" : "failed", j.success ? "done" : "error");
        ingProgressEl.innerHTML = `<pre>${escapeHtml(JSON.stringify({
          stored_at: d.stored_at, size_bytes: d.size_bytes,
          chunks: d.chunks_processed, error: j.error,
        }, null, 2))}</pre>`;
        return;
      }

      // text-only path: async queue
      if (!docId) {
        setIngStatus("doc_id required for text-only ingest", "error");
        return;
      }
      const body = { doc_id: docId, content, tenant_id: tenant, force };
      setIngStatus("enqueueing…", "running");
      const r = await fetch("/api/v1/ingest/async", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || j.error || `HTTP ${r.status}`);
      const taskId = (j.data && j.data.task_id) || j.trace_id;
      if (!taskId) throw new Error("no task_id in response");
      setIngStatus(`queued task=${taskId}`, "running");
      await pollIngestStatus(taskId);
    } catch (e) {
      setIngStatus(`error: ${e.message}`, "error");
    } finally {
      ingSubmitBtn.disabled = false;
    }
  };

  ingSubmitBtn.addEventListener("click", submitIngest);

  // ── wiring ───────────────────────────────────────────────────────────────
  sendBtn.addEventListener("click", run);
  clearBtn.addEventListener("click", () => {
    eventsEl.innerHTML = "";
    answerEl.textContent = "";
    sourcesEl.innerHTML = "";
    rawEl.textContent = "";
    answerPanel.classList.add("hidden");
    fbStatus.textContent = "";
    setStatus("idle", "idle");
  });
  queryInput.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") run();
  });
})();
