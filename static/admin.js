(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const escapeHtml = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

  const setStatus = (el, label, cls) => {
    if (!el) return;
    el.textContent = label;
    el.className = `status ${cls}`;
  };

  const jget = async (url) => {
    const r = await fetch(url);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || j.error || `HTTP ${r.status}`);
    return j.data ?? j;
  };

  const jpost = async (url, body, method = "POST") => {
    const r = await fetch(url, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || j.error || `HTTP ${r.status}`);
    return j.data ?? j;
  };

  // ── tabs ─────────────────────────────────────────────────────────────────
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
      document
        .querySelectorAll(".pane")
        .forEach((p) => p.classList.toggle("active", p.dataset.pane === target));
    });
  });

  // ── SYSTEM pane ──────────────────────────────────────────────────────────
  const readinessOut = $("readiness-out");
  const statsOut = $("stats-out");
  const cacheOut = $("cache-out");

  const refreshStatus = async () => {
    readinessOut.textContent = "loading…";
    statsOut.textContent = "loading…";
    try {
      const r = await fetch("/api/v1/readiness");
      readinessOut.textContent = JSON.stringify(await r.json(), null, 2);
    } catch (e) {
      readinessOut.textContent = `error: ${e.message}`;
    }
    try {
      statsOut.textContent = JSON.stringify(await jget("/api/v1/stats"), null, 2);
    } catch (e) {
      statsOut.textContent = `error: ${e.message}`;
    }
  };

  $("btn-refresh-status").addEventListener("click", refreshStatus);
  $("btn-clear-cache").addEventListener("click", async () => {
    if (!confirm("DELETE /api/v1/cache — wipe all rag:* Redis keys?")) return;
    cacheOut.textContent = "running…";
    try {
      const d = await jpost("/api/v1/cache", undefined, "DELETE");
      cacheOut.textContent = JSON.stringify(d, null, 2);
    } catch (e) {
      cacheOut.textContent = `error: ${e.message}`;
    }
  });

  // ── VERSIONS pane ────────────────────────────────────────────────────────
  const verDocId = $("ver-docid");
  const versionsTable = $("versions-table");
  const versionDetail = $("version-detail");
  let selectedVersion = null;

  const renderVersionsTable = (versions) => {
    if (!versions || !versions.length) {
      versionsTable.innerHTML = "<em>(no versions)</em>";
      return;
    }
    const rows = versions
      .map(
        (v) => `
          <tr class="clickable" data-version="${escapeHtml(v.version)}">
            <td>${escapeHtml(v.version)}</td>
            <td>${v.is_current ? "✓" : ""}</td>
            <td>${escapeHtml(v.chunk_count)}</td>
            <td>${escapeHtml(v.checksum).slice(0, 12)}…</td>
            <td>${new Date((v.ingested_at || 0) * 1000).toISOString()}</td>
            <td>${escapeHtml(v.note || "")}</td>
            <td>${escapeHtml(v.user_id || "")}</td>
          </tr>`
      )
      .join("");
    versionsTable.innerHTML = `
      <table>
        <thead><tr>
          <th>version</th><th>current</th><th>chunks</th><th>checksum</th>
          <th>ingested_at</th><th>note</th><th>user</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    versionsTable.querySelectorAll("tr.clickable").forEach((tr) => {
      tr.addEventListener("click", async () => {
        versionsTable.querySelectorAll("tr").forEach((r) => r.classList.remove("selected"));
        tr.classList.add("selected");
        selectedVersion = tr.dataset.version;
        const docId = verDocId.value.trim();
        try {
          versionDetail.textContent = "loading…";
          const d = await jget(`/api/v1/docs/${encodeURIComponent(docId)}/versions/${encodeURIComponent(selectedVersion)}`);
          versionDetail.textContent = JSON.stringify(d, null, 2);
        } catch (e) {
          versionDetail.textContent = `error: ${e.message}`;
        }
      });
    });
  };

  $("btn-list-versions").addEventListener("click", async () => {
    const docId = verDocId.value.trim();
    if (!docId) {
      versionsTable.innerHTML = "<em>doc_id required</em>";
      return;
    }
    try {
      const d = await jget(`/api/v1/docs/${encodeURIComponent(docId)}/versions`);
      renderVersionsTable(d.versions || d);
    } catch (e) {
      versionsTable.innerHTML = `<strong style="color:var(--danger)">${escapeHtml(e.message)}</strong>`;
    }
  });

  $("btn-scan-kb").addEventListener("click", async () => {
    try {
      const d = await jpost("/api/v1/knowledge/scan");
      alert("scan enqueued: " + JSON.stringify(d));
    } catch (e) {
      alert("error: " + e.message);
    }
  });

  $("btn-rollback").addEventListener("click", async () => {
    const docId = verDocId.value.trim();
    const target = parseInt($("rollback-target").value, 10);
    const statusEl = $("rollback-status");
    if (!docId || !target) {
      setStatus(statusEl, "doc_id + target_version required", "error");
      return;
    }
    if (!confirm(`Rollback ${docId} to version ${target}?`)) return;
    setStatus(statusEl, "running…", "running");
    try {
      const d = await jpost(`/api/v1/docs/${encodeURIComponent(docId)}/rollback`, { target_version: target });
      setStatus(statusEl, `done: ${d.message || "ok"}`, "done");
    } catch (e) {
      setStatus(statusEl, `error: ${e.message}`, "error");
    }
  });

  // ── ANNOTATION pane ──────────────────────────────────────────────────────
  const annTask = $("ann-task");
  const annForm = $("ann-form");
  const annStats = $("ann-stats");
  let currentTaskId = null;

  const renderTask = (task) => {
    if (!task) {
      annTask.innerHTML = "<em>(queue empty)</em>";
      annForm.classList.add("hidden");
      currentTaskId = null;
      return;
    }
    currentTaskId = task.task_id;
    const userCommentBlock = task.user_comment
      ? `<div class="ann-field" style="background:#fff8e1;padding:0.5em;border-left:3px solid #ffa000;"><strong>👎 用户备注:</strong><br>${escapeHtml(task.user_comment)}</div>`
      : "";
    annTask.innerHTML = `
      <div class="ann-field"><strong>task_id:</strong> <code>${escapeHtml(task.task_id)}</code></div>
      <div class="ann-field"><strong>tenant_id:</strong> ${escapeHtml(task.tenant_id || "—")}</div>
      <div class="ann-field"><strong>source:</strong> ${escapeHtml(task.source || "—")}</div>
      ${userCommentBlock}
      <div class="ann-field"><strong>question:</strong><br>${escapeHtml(task.question || "")}</div>
      <div class="ann-field"><strong>answer:</strong><br>${escapeHtml(task.answer || "")}</div>
      <div class="ann-field"><strong>contexts:</strong>
        <pre>${escapeHtml(JSON.stringify(task.contexts || [], null, 2))}</pre>
      </div>`;
    annForm.classList.remove("hidden");
  };

  $("btn-ann-next").addEventListener("click", async () => {
    const tenant = $("ann-tenant").value.trim();
    try {
      const url = "/api/v1/annotation/tasks/next" + (tenant ? `?tenant_id=${encodeURIComponent(tenant)}` : "");
      const d = await jget(url);
      renderTask(d);
    } catch (e) {
      annTask.innerHTML = `<strong style="color:var(--danger)">${escapeHtml(e.message)}</strong>`;
    }
  });

  $("btn-ann-stats").addEventListener("click", async () => {
    try {
      const d = await jget("/api/v1/annotation/stats");
      annStats.textContent = `stats: ${JSON.stringify(d)}`;
    } catch (e) {
      annStats.textContent = `error: ${e.message}`;
    }
  });

  $("btn-ann-submit").addEventListener("click", async () => {
    if (!currentTaskId) return;
    const status = $("ann-status");
    setStatus(status, "submitting…", "running");
    try {
      await jpost(`/api/v1/annotation/tasks/${encodeURIComponent(currentTaskId)}/result`, {
        faithfulness: parseFloat($("ann-faith").value),
        answer_quality: parseFloat($("ann-quality").value),
        annotator_id: $("ann-annotator").value.trim() || "admin-ui",
        comment: $("ann-comment").value.trim(),
      });
      setStatus(status, "submitted", "done");
      renderTask(null);
    } catch (e) {
      setStatus(status, `error: ${e.message}`, "error");
    }
  });

  $("btn-ann-skip").addEventListener("click", async () => {
    if (!currentTaskId) return;
    const status = $("ann-status");
    try {
      await jpost(`/api/v1/annotation/tasks/${encodeURIComponent(currentTaskId)}/skip`);
      setStatus(status, "skipped", "done");
      renderTask(null);
    } catch (e) {
      setStatus(status, `error: ${e.message}`, "error");
    }
  });

  // ── A/B pane ─────────────────────────────────────────────────────────────
  const abList = $("ab-list");
  const abDetail = $("ab-detail");
  const abExpId = $("ab-exp-id");

  const renderExperiments = (experiments) => {
    if (!experiments || !experiments.length) {
      abList.innerHTML = "<em>(no experiments)</em>";
      return;
    }
    const rows = experiments
      .map(
        (e) => `
          <tr class="clickable" data-id="${escapeHtml(e.experiment_id || e.id || "")}">
            <td>${escapeHtml(e.experiment_id || e.id || "")}</td>
            <td>${escapeHtml(e.name || "")}</td>
            <td>${escapeHtml(e.status || "")}</td>
            <td>${escapeHtml((e.variants || []).map((v) => v.variant_id).join(", "))}</td>
            <td>${escapeHtml(e.tenant_id || "")}</td>
          </tr>`
      )
      .join("");
    abList.innerHTML = `
      <table>
        <thead><tr><th>id</th><th>name</th><th>status</th><th>variants</th><th>tenant</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    abList.querySelectorAll("tr.clickable").forEach((tr) => {
      tr.addEventListener("click", () => {
        abList.querySelectorAll("tr").forEach((r) => r.classList.remove("selected"));
        tr.classList.add("selected");
        abExpId.value = tr.dataset.id;
      });
    });
  };

  $("btn-ab-list").addEventListener("click", async () => {
    try {
      const d = await jget("/api/v1/ab/experiments");
      renderExperiments(d.experiments || d);
    } catch (e) {
      abList.innerHTML = `<strong style="color:var(--danger)">${escapeHtml(e.message)}</strong>`;
    }
  });

  $("btn-ab-create").addEventListener("click", async () => {
    const status = $("ab-create-status");
    let variants;
    try {
      variants = JSON.parse($("ab-variants").value);
    } catch (e) {
      setStatus(status, `JSON error: ${e.message}`, "error");
      return;
    }
    setStatus(status, "creating…", "running");
    try {
      const d = await jpost("/api/v1/ab/experiments", {
        name: $("ab-name").value.trim(),
        description: $("ab-desc").value.trim(),
        tenant_id: $("ab-tenant").value.trim(),
        variants,
      });
      abExpId.value = d.experiment_id || "";
      setStatus(status, `created ${d.experiment_id}`, "done");
    } catch (e) {
      setStatus(status, `error: ${e.message}`, "error");
    }
  });

  const expAction = async (suffix, method = "POST") => {
    const id = abExpId.value.trim();
    if (!id) {
      abDetail.textContent = "experiment_id required";
      return;
    }
    abDetail.textContent = "loading…";
    try {
      const d =
        method === "GET"
          ? await jget(`/api/v1/ab/experiments/${encodeURIComponent(id)}${suffix}`)
          : await jpost(`/api/v1/ab/experiments/${encodeURIComponent(id)}${suffix}`, undefined, method);
      abDetail.textContent = JSON.stringify(d, null, 2);
    } catch (e) {
      abDetail.textContent = `error: ${e.message}`;
    }
  };

  $("btn-ab-start").addEventListener("click", () => expAction("/start"));
  $("btn-ab-stop").addEventListener("click", () => expAction("/stop"));
  $("btn-ab-stats").addEventListener("click", () => expAction("/stats", "GET"));
  $("btn-ab-winner").addEventListener("click", () => expAction("/winner", "GET"));

  $("btn-ab-feedback").addEventListener("click", async () => {
    const id = abExpId.value.trim();
    const status = $("ab-fb-status");
    if (!id) {
      setStatus(status, "experiment_id required", "error");
      return;
    }
    setStatus(status, "sending…", "running");
    try {
      await jpost(`/api/v1/ab/experiments/${encodeURIComponent(id)}/feedback`, {
        variant_id: $("ab-fb-variant").value.trim(),
        session_id: $("ab-fb-session").value.trim(),
        feedback: parseInt($("ab-fb-value").value, 10),
      });
      setStatus(status, "recorded", "done");
    } catch (e) {
      setStatus(status, `error: ${e.message}`, "error");
    }
  });

  // ── init ─────────────────────────────────────────────────────────────────
  refreshStatus();
})();
