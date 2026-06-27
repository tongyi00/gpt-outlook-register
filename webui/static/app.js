// 团子喵的 WebUI 交互逻辑 ~

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

// ──────────────────────── 工具 ────────────────────────

async function api(path, opts = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || resp.statusText);
  return data;
}

function fmtTime(ts) {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false });
}

function fmtLogNow() {
  return new Date().toLocaleTimeString("zh-CN", { hour12: false });
}

function ensureLogTime(text) {
  const s = String(text || "");
  return /^\d{1,2}:\d{2}:\d{2}\s/.test(s) ? s : `${fmtLogNow()} ${s}`;
}

function logLine(text, kind = "") {
  const box = $("#logBox");
  const div = document.createElement("div");
  div.className = "line " + kind;
  div.textContent = ensureLogTime(text);
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function classifyLog(line) {
  const l = line.toLowerCase();
  if (l.includes("error") || l.includes("失败") || l.includes("拒绝")) return "err";
  if (l.includes("warning") || l.includes("warn")) return "warn";
  if (l.includes("成功") || l.includes("完成") || l.includes("命中") || l.includes("ok")) return "ok";
  return "";
}

// ──────────────────────── 统计栏 ────────────────────────

async function refreshStats() {
  try {
    const { stats } = await api("/api/stats");
    const items = [
      { v: stats.total,     cls: "" },
      { v: stats.available, cls: "ok" },
      { v: stats.in_use,    cls: "warn" },
      { v: stats.done,      cls: "done" },
      { v: stats.failed,    cls: "bad" },
    ];
    $$("#statsBar .pill").forEach((el, i) => {
      el.querySelector("b").textContent = items[i].v;
    });
  } catch (e) {
    console.error("stats:", e);
  }
}

// ──────────────────────── 导入 ────────────────────────

$("#btnImport").addEventListener("click", async () => {
  const text = $("#importText").value.trim();
  if (!text) {
    $("#importResult").textContent = "请输入要导入的接码号";
    return;
  }
  $("#btnImport").disabled = true;
  $("#importResult").textContent = "导入中...";
  try {
    const r = await api("/api/import", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    $("#importResult").textContent =
      `✅ 解析 ${r.parsed} 行，新增 ${r.inserted}，更新 ${r.updated}，跳过 ${r.skipped}`;
    $("#importResult").className = "result ok";
    $("#importText").value = "";
    refreshStats();
    refreshPool();
  } catch (e) {
    $("#importResult").textContent = "❌ " + e.message;
    $("#importResult").className = "result bad";
  } finally {
    $("#btnImport").disabled = false;
  }
});

// ──────────────────────── 触发注册 ────────────────────────

let currentEs = null;
let currentRunId = null;

$("#btnRun").addEventListener("click", async () => {
  const email = $("#regEmail").value.trim();
  const opts = {
    email: email || null,
    proxy: $("#regProxy").value.trim(),
    proxy_pool: $("#autoProxyPool").value,
    otp_timeout: parseInt($("#regOtpTimeout").value || "180", 10),
    want_access_token: true,
    want_session_token: true,
    want_refresh_token: true,
  };
  $("#btnRun").disabled = true;
  $("#btnStopRun").disabled = true;
  $("#runStatus").textContent = "启动中...";
  $("#runStatus").className = "result";
  $("#logBox").innerHTML = "";

  try {
    const r = await api("/api/register", {
      method: "POST",
      body: JSON.stringify(opts),
    });
    currentRunId = r.run_id;
    $("#runStatus").textContent = `🚀 已启动 run_id=${r.run_id} email=${r.email}`;
    logLine(`[client] 启动注册 run_id=${r.run_id} email=${r.email}`, "evt");
    $("#btnStopRun").disabled = false;
    streamRun(r.run_id);
  } catch (e) {
    $("#runStatus").textContent = "❌ " + e.message;
    $("#runStatus").className = "result bad";
    $("#btnRun").disabled = false;
    $("#btnStopRun").disabled = true;
  }
});

$("#btnStopRun").addEventListener("click", async () => {
  if (!currentRunId) return;
  const runId = currentRunId;
  $("#btnStopRun").disabled = true;
  $("#btnStopRun").textContent = "⏳ 停止中...";
  try {
    await api(`/api/runs/${encodeURIComponent(runId)}/stop`, { method: "POST" });
    $("#runStatus").textContent = `⏹ 已请求停止 run_id=${runId}`;
    $("#runStatus").className = "result warn";
    logLine(`[client] ⏹ 已请求停止 run_id=${runId}`, "warn");
  } catch (e) {
    $("#runStatus").textContent = "❌ 停止失败: " + e.message;
    $("#runStatus").className = "result bad";
    $("#btnStopRun").disabled = false;
  } finally {
    $("#btnStopRun").textContent = "⏹ 停止当前账号";
  }
});

function streamRun(runId) {
  if (currentEs) { try { currentEs.close(); } catch (_) {} }
  const es = new EventSource(`/api/runs/${runId}/stream`);
  currentEs = es;

  es.addEventListener("log", (e) => {
    try {
      const d = JSON.parse(e.data);
      if (!d.line) return;
      logLine(d.line, classifyLog(d.line));
    } catch (_) {}
  });

  es.addEventListener("status", (e) => {
    try {
      const d = JSON.parse(e.data);
      if (d.kind === "done") {
        const s = `✅ 注册完成: access_token=${d.access_token_len}${d.partial ? "  (部分凭证)" : ""}`;
        const buttons = [];
        if (d.access_token_len > 0)  buttons.push(`<button class="quick-copy" data-email="${d.email}" data-field="access_token">📋 复制 access_token</button>`);
        $("#runStatus").innerHTML = `<span class="ok">${s}</span>${buttons.length ? "<br>" + buttons.join(" ") : ""}`;
        logLine("[client] " + s, "evt");
      } else if (d.kind === "error") {
        $("#runStatus").textContent = "❌ " + d.message;
        $("#runStatus").className = "result bad";
        logLine("[client] ❌ " + d.message, "err");
      } else if (d.kind === "stopped") {
        $("#runStatus").textContent = "⏹ " + (d.message || "已停止当前注册");
        $("#runStatus").className = "result warn";
        $("#btnStopRun").disabled = true;
        logLine("[client] ⏹ " + (d.message || "已停止当前注册"), "warn");
      } else if (d.kind === "phase") {
        logLine(`[client] phase=${d.phase} email=${d.email}`, "evt");
      }
    } catch (_) {}
  });

  es.addEventListener("end", () => {
    try { es.close(); } catch (_) {}
    currentEs = null;
    if (currentRunId === runId) currentRunId = null;
    $("#btnRun").disabled = false;
    $("#btnStopRun").disabled = true;
    refreshStats();
    refreshPool();
    refreshRegistered();
    refreshRuns();
  });

  es.onerror = () => {
    try { es.close(); } catch (_) {}
    currentEs = null;
    if (currentRunId === runId) currentRunId = null;
    $("#btnRun").disabled = false;
    $("#btnStopRun").disabled = true;
  };
}

// 状态栏快捷复制按钮（注册完成后直接显示在这里，不用切 Tab）
$("#runStatus").addEventListener("click", async (e) => {
  const copyBtn = e.target.closest("button.quick-copy");
  if (copyBtn) {
    const email = copyBtn.dataset.email;
    const field = copyBtn.dataset.field;
    try {
      const cred = await _loadCred(email);
      const val = cred[field] || "";
      if (!val) { alert(`${field} 为空`); return; }
      await _copyText(val, copyBtn);
    } catch (err) { alert("加载凭证失败: " + err.message); }
  }
});

// ──────────────────────── Tabs ────────────────────────

const PAGE_META = {
  register: ["ChatGPT", "单个注册 + 自动跑号池"],
  pool: ["号池", "Outlook 接码号"],
  registered: ["运行记录", ""],
  customsms: ["手机号池", ""],
  sessionlink: ["链接生成", "循环生成付款链接"],
  proxypool: ["数据导入", ""],
  runs: ["运行记录", ""],
  mailcfg: ["数据导入", ""],
  smscfg: ["数据导入", ""],
  exportcfg: ["自动导出", "CPA 与 SUB2API 面板配置"],
};

const HIDE_STATS_TABS = new Set(["customsms", "sessionlink", "mailcfg", "exportcfg"]);

function setDataImportView(view) {
  const target = ["mail", "sms", "proxy"].includes(view) ? view : "mail";
  $$("input[name=\"dataImportView\"]").forEach((input) => {
    input.checked = input.value === target;
  });
  $$(".data-import-panel").forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.importPanel !== target);
  });
}

function activateTab(tabName) {
  let dataImportView = null;
  if (tabName === "runs") tabName = "registered";
  if (tabName === "smscfg") {
    tabName = "mailcfg";
    dataImportView = "sms";
  }
  if (tabName === "proxypool") {
    tabName = "mailcfg";
    dataImportView = "proxy";
  }
  const target = $("#tab-" + tabName);
  if (!target) return;
  $$(".tab").forEach((x) => x.classList.toggle("active", x.dataset.tab === tabName));
  $$(".tab-content").forEach((c) => c.classList.add("hidden"));
  target.classList.remove("hidden");
  $("#statsBar")?.classList.toggle("hidden", HIDE_STATS_TABS.has(tabName));

  const [title, sub] = PAGE_META[tabName] || ["", ""];
  if ($("#pageTitle")) $("#pageTitle").textContent = title;
  if ($("#pageSub")) $("#pageSub").textContent = sub;

  if (tabName === "register") {
    refreshRegistered();
    loadExportConfig();
  }
  if (tabName === "pool") refreshPool();
  if (tabName === "registered") {
    refreshRuns();
  }
  if (tabName === "mailcfg") {
    loadMailConfig();
    loadSmsConfig();
    const checked = document.querySelector("input[name=\"dataImportView\"]:checked");
    setDataImportView(dataImportView || checked?.value || "mail");
  }
  if (tabName === "customsms") loadCustomSmsPool();
  if (tabName === "sessionlink") {
    loadSessionLinkModes();
    refreshSessionLinkStatus();
    ensureSessionLinkPolling();
  }
  if (tabName === "exportcfg") loadExportConfig();
}

$$(".tab").forEach((t) => {
  t.addEventListener("click", (e) => {
    e.preventDefault();
    activateTab(t.dataset.tab);
  });
});

$$("input[name=\"dataImportView\"]").forEach((input) => {
  input.addEventListener("change", (e) => {
    if (e.target.checked) setDataImportView(e.target.value);
  });
});

// ──────────────────────── 链接生成 ────────────────────────

let sessionLinkModesLoaded = false;
let sessionLinkPollTimer = null;

async function loadSessionLinkModes() {
  if (sessionLinkModesLoaded) return;
  try {
    const { modes } = await api("/api/session-link/payment-modes");
    const select = $("#sessionLinkMode");
    const names = Object.keys(modes || {});
    if (!select || names.length === 0) return;
    select.innerHTML = names.map((name) => {
      const cfg = modes[name] || {};
      const suffix = cfg.country && cfg.currency ? ` · ${cfg.country}/${cfg.currency}` : "";
      return `<option value="${escapeHtml(name)}">${escapeHtml(name + suffix)}</option>`;
    }).join("");
    select.value = "PayPal 长链接 US/USD";
    sessionLinkModesLoaded = true;
  } catch (err) {
    console.error("session link modes:", err);
  }
}

function _sessionLinkPayload() {
  return {
    session_text: $("#sessionLinkInput").value.trim(),
    payment_mode: $("#sessionLinkMode").value,
    target_amount: $("#sessionLinkTargetAmount").value.trim() || "0",
    thread_count: parseInt($("#sessionLinkThreadCount").value || "1", 10),
    delay_seconds: parseInt($("#sessionLinkDelaySeconds").value || "2", 10),
    payment_proxy_pool: $("#sessionLinkPaymentProxyPool").value.trim(),
  };
}

function _sessionLinkStatusText(state) {
  const statusMap = {
    idle: "未运行",
    running: "运行中",
    done: "已完成",
    failed: "失败",
    stopped: "已停止",
  };
  const title = statusMap[state.status] || state.status || "未运行";
  const parts = [
    title,
    `轮次 ${state.attempt || 0}`,
    `成功 ${state.success_count || 0}`,
    `待重试 ${state.pending_count || 0}`,
  ];
  if (state.last_error) parts.push(`最近错误: ${state.last_error}`);
  return parts.join("  |  ");
}

function _sessionLinkResultHtml(state) {
  const results = state.results || [];
  if (!results.length) return '<div class="empty">暂无生成结果</div>';
  const summary = `
    <div class="session-link-summary">
      <span>总数 ${escapeHtml(state.total || 0)} / 成功 ${escapeHtml(state.success_count || 0)} / 失败 ${escapeHtml(state.failure_count || 0)}</span>
      <span>线程 ${escapeHtml(state.thread_count || 1)}</span>
    </div>
  `;
  const rows = results.map((item) => {
    const ok = !item.error;
    const cls = ok ? "ok" : "bad";
    const title = `#${Number(item.index || 0) + 1} ${ok ? "成功" : "失败"}`;
    const url = item.long_url || "";
    const actions = ok ? `
      <div class="session-link-item-actions">
        <button data-session-link-copy="${escapeHtml(url)}" type="button">复制链接</button>
        <button data-session-link-open="${escapeHtml(url)}" type="button">打开链接</button>
      </div>
    ` : "";
    return `
      <div class="session-link-item ${cls}">
        <div class="session-link-item-head">
          <span>${escapeHtml(title)}</span>
          <span class="status-chip muted">${escapeHtml(item.token_preview || "")}</span>
        </div>
        ${ok ? `<div class="session-link-url">${escapeHtml(url)}</div>` : `<div class="session-link-error">${escapeHtml(item.error || "生成失败")}</div>`}
        <div class="session-link-meta">模式 ${escapeHtml(item.payment_mode || state.payment_mode || "")} · 金额 ${escapeHtml(item.stripe_amount || "")} · 目标 ${escapeHtml(item.target_amount || "")} · 代理 ${escapeHtml(item.proxy_used || "直连")}</div>
        ${actions}
      </div>
    `;
  }).join("");
  return summary + rows;
}

function _sessionLinkLogsHtml(logs) {
  if (!logs || logs.length === 0) return "";
  return logs.map((row) => {
    const time = row.time ? fmtTime(row.time) : "-";
    return `<div class="session-link-log-row ${escapeHtml(row.kind || "")}">${escapeHtml(time)} ${escapeHtml(row.title || "")} ${escapeHtml(row.message || "")}</div>`;
  }).join("");
}

function renderSessionLinkStatus(state) {
  const running = !!state.running;
  $("#sessionLinkStatus").textContent = _sessionLinkStatusText(state);
  $("#sessionLinkStatus").className = `status-panel ${state.status === "done" ? "ok" : state.status === "failed" ? "bad" : ""}`;
  $("#sessionLinkResult").innerHTML = _sessionLinkResultHtml(state);
  $("#sessionLinkLogs").innerHTML = _sessionLinkLogsHtml(state.logs || []);
  $("#sessionLinkRunOnce").disabled = running;
  $("#sessionLinkStart").disabled = running;
  $("#sessionLinkStop").disabled = !running;
}

async function refreshSessionLinkStatus() {
  try {
    const state = await api("/api/session-link/status");
    renderSessionLinkStatus(state);
  } catch (err) {
    $("#sessionLinkStatus").textContent = "状态加载失败: " + err.message;
    $("#sessionLinkStatus").className = "status-panel bad";
  }
}

function ensureSessionLinkPolling() {
  if (sessionLinkPollTimer) return;
  sessionLinkPollTimer = setInterval(() => {
    const active = !$("#tab-sessionlink")?.classList.contains("hidden");
    const running = !$("#sessionLinkStop")?.disabled;
    if (active || running) refreshSessionLinkStatus();
  }, 2000);
}

$("#sessionLinkRunOnce")?.addEventListener("click", async () => {
  if (!$("#sessionLinkInput").value.trim()) {
    $("#sessionLinkStatus").textContent = "请先粘贴 Session JSON / Access Token";
    $("#sessionLinkStatus").className = "status-panel bad";
    return;
  }
  $("#sessionLinkRunOnce").disabled = true;
  $("#sessionLinkStatus").textContent = "生成中...";
  try {
    const result = await api("/api/session-link/run-once", {
      method: "POST",
      body: JSON.stringify(_sessionLinkPayload()),
    });
    renderSessionLinkStatus({
      running: false,
      status: result.success_count > 0 ? "done" : "failed",
      attempt: 1,
      total: result.total,
      success_count: result.success_count,
      failure_count: result.failure_count,
      pending_count: result.failure_count,
      thread_count: result.thread_count,
      payment_mode: result.payment_mode,
      results: result.results,
      logs: [],
    });
  } catch (err) {
    $("#sessionLinkStatus").textContent = "生成失败: " + err.message;
    $("#sessionLinkStatus").className = "status-panel bad";
  } finally {
    $("#sessionLinkRunOnce").disabled = false;
  }
});

$("#sessionLinkStart")?.addEventListener("click", async () => {
  if (!$("#sessionLinkInput").value.trim()) {
    $("#sessionLinkStatus").textContent = "请先粘贴 Session JSON / Access Token";
    $("#sessionLinkStatus").className = "status-panel bad";
    return;
  }
  $("#sessionLinkStart").disabled = true;
  $("#sessionLinkStatus").textContent = "启动循环中...";
  try {
    const state = await api("/api/session-link/start", {
      method: "POST",
      body: JSON.stringify(_sessionLinkPayload()),
    });
    renderSessionLinkStatus(state);
    ensureSessionLinkPolling();
  } catch (err) {
    $("#sessionLinkStatus").textContent = "启动失败: " + err.message;
    $("#sessionLinkStatus").className = "status-panel bad";
    $("#sessionLinkStart").disabled = false;
  }
});

$("#sessionLinkStop")?.addEventListener("click", async () => {
  $("#sessionLinkStop").disabled = true;
  try {
    const state = await api("/api/session-link/stop", { method: "POST" });
    renderSessionLinkStatus(state);
  } catch (err) {
    $("#sessionLinkStatus").textContent = "停止失败: " + err.message;
    $("#sessionLinkStatus").className = "status-panel bad";
  }
});

$("#sessionLinkResult")?.addEventListener("click", async (e) => {
  const copyBtn = e.target.closest("button[data-session-link-copy]");
  if (copyBtn) {
    await _copyText(copyBtn.dataset.sessionLinkCopy, copyBtn);
    return;
  }
  const openBtn = e.target.closest("button[data-session-link-open]");
  if (openBtn) {
    window.open(openBtn.dataset.sessionLinkOpen, "_blank", "noopener");
  }
});

// ──────────────────────── 号池列表 ────────────────────────

async function refreshPool() {
  const status = $("#poolFilter").value;
  const { items } = await api(`/api/accounts?status=${encodeURIComponent(status)}`);
  const tb = $("#poolTable tbody");
  tb.innerHTML = "";
  for (const r of items) {
    const tr = document.createElement("tr");
    const canReset = (r.status === "done" || r.status === "failed");
    tr.innerHTML = `
      <td><input type="checkbox" class="pool-check" data-email="${r.email}"></td>
      <td>${r.email}</td>
      <td><span class="status ${r.status}">${r.status}</span></td>
      <td title="${r.fail_reason || ''}">${(r.fail_reason || '').slice(0, 50)}</td>
      <td>
        <button data-act="use" data-email="${r.email}">使用</button>
        ${canReset ? `<button data-act="reset" data-email="${r.email}" title="改回 available 重新注册">🔄 重置</button>` : ""}
        <button data-act="del" data-email="${r.email}">删除</button>
      </td>
    `;
    tb.appendChild(tr);
  }
  $("#poolSelectAll").checked = false;
  _updateSelCount();
}
$("#btnRefreshPool").addEventListener("click", refreshPool);
$("#poolFilter").addEventListener("change", refreshPool);

$("#btnResetFailed").addEventListener("click", async () => {
  if (!confirm("把所有 failed 号重置为 available？")) return;
  $("#poolActionResult").textContent = "处理中...";
  $("#poolActionResult").className = "result";
  try {
    const r = await api("/api/accounts/reset_failed", { method: "POST" });
    $("#poolActionResult").textContent = `✅ 重置 ${r.reset} 个号为 available`;
    $("#poolActionResult").className = "result ok";
    refreshPool(); refreshStats();
  } catch (e) {
    $("#poolActionResult").textContent = "❌ " + e.message;
    $("#poolActionResult").className = "result bad";
  }
});

$("#btnReleaseStale").addEventListener("click", async () => {
  $("#poolActionResult").textContent = "处理中...";
  $("#poolActionResult").className = "result";
  try {
    const r = await api("/api/accounts/release_stale", { method: "POST" });
    $("#poolActionResult").textContent = `✅ 释放 ${r.released} 个卡死号`;
    $("#poolActionResult").className = "result ok";
    refreshPool(); refreshStats();
  } catch (e) {
    $("#poolActionResult").textContent = "❌ " + e.message;
    $("#poolActionResult").className = "result bad";
  }
});

// ── 号池：复选框选择 + 批量删除 ──

function _selectedEmails() {
  return Array.from(document.querySelectorAll(".pool-check:checked"))
    .map(c => c.dataset.email);
}
function _updateSelCount() {
  const n = _selectedEmails().length;
  $("#selCount").textContent = n;
  $("#selCount2").textContent = n;
  $("#btnDeleteSelected").disabled = n === 0;
  $("#btnResetSelected").disabled = n === 0;
}
$("#poolTable").addEventListener("change", (e) => {
  if (e.target.classList.contains("pool-check")) _updateSelCount();
});
$("#poolSelectAll").addEventListener("change", (e) => {
  document.querySelectorAll(".pool-check").forEach(c => c.checked = e.target.checked);
  _updateSelCount();
});

$("#btnResetSelected").addEventListener("click", async () => {
  const emails = _selectedEmails();
  if (!emails.length) return;
  if (!confirm(`重置选中的 ${emails.length} 个号为 available？\n（号会重新可用，已保存的凭证不变）`)) return;
  $("#poolActionResult").textContent = "重置中...";
  $("#poolActionResult").className = "result";
  try {
    const r = await api("/api/accounts/bulk_reset", {
      method: "POST",
      body: JSON.stringify({ emails }),
    });
    $("#poolActionResult").textContent = `✅ 已重置 ${r.reset} 个号`;
    $("#poolActionResult").className = "result ok";
    refreshPool(); refreshStats();
  } catch (e) {
    $("#poolActionResult").textContent = "❌ " + e.message;
    $("#poolActionResult").className = "result bad";
  }
});

$("#btnDeleteSelected").addEventListener("click", async () => {
  const emails = _selectedEmails();
  if (!emails.length) return;
  if (!confirm(`确定删除选中的 ${emails.length} 个号？(不可恢复)`)) return;
  $("#poolActionResult").textContent = "删除中...";
  $("#poolActionResult").className = "result";
  try {
    const r = await api("/api/accounts/bulk_delete", {
      method: "POST",
      body: JSON.stringify({ emails }),
    });
    $("#poolActionResult").textContent = `✅ 已删除 ${r.deleted} 个号`;
    $("#poolActionResult").className = "result ok";
    refreshPool(); refreshStats();
  } catch (e) {
    $("#poolActionResult").textContent = "❌ " + e.message;
    $("#poolActionResult").className = "result bad";
  }
});

$("#btnBulkDelStatus").addEventListener("click", async () => {
  const status = $("#bulkDelStatus").value;
  if (!status) {
    $("#poolActionResult").textContent = "请先选择要删除的状态";
    $("#poolActionResult").className = "result bad";
    return;
  }
  const tip = status === "all"
    ? "⚠️ 这会删除号池里所有号（含未注册的），确定？"
    : `确定删除全部 ${status} 状态的号？`;
  if (!confirm(tip)) return;
  $("#poolActionResult").textContent = "删除中...";
  $("#poolActionResult").className = "result";
  try {
    const r = await api("/api/accounts/bulk_delete", {
      method: "POST",
      body: JSON.stringify({ status }),
    });
    $("#poolActionResult").textContent = `✅ 已删除 ${r.deleted} 个 ${status} 号`;
    $("#poolActionResult").className = "result ok";
    $("#bulkDelStatus").value = "";
    refreshPool(); refreshStats();
  } catch (e) {
    $("#poolActionResult").textContent = "❌ " + e.message;
    $("#poolActionResult").className = "result bad";
  }
});

$("#poolTable").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  const email = btn.dataset.email;
  if (btn.dataset.act === "use") {
    $("#regEmail").value = email;
    activateTab("register");
    document.querySelector(".content")?.scrollTo({ top: 0, behavior: "smooth" });
  } else if (btn.dataset.act === "reset") {
    if (!confirm(`重置 ${email} 为 available？\n（号会重新可用，但已保存的凭证不变）`)) return;
    try {
      await api(`/api/accounts/reset/${encodeURIComponent(email)}`, { method: "POST" });
      refreshPool();
      refreshStats();
    } catch (err) {
      alert("重置失败: " + err.message);
    }
  } else if (btn.dataset.act === "del") {
    if (!confirm(`删除 ${email}？`)) return;
    await api(`/api/accounts/${encodeURIComponent(email)}`, { method: "DELETE" });
    refreshPool();
    refreshStats();
  }
});

// ──────────────────────── 注册结果列表 ────────────────────────

async function refreshRegistered() {
  const { items } = await api("/api/registered");
  const filter = document.querySelector("input[name='regFilter']:checked")?.value || "all";

  // 按筛选条件过滤
  let filtered = items;
  if (filter === "has_rt") {
    filtered = items.filter(r => r.rt_len > 0);
  } else if (filter === "no_rt") {
    filtered = items.filter(r => r.rt_len === 0);
  }

  const tb = $("#regTable tbody");
  tb.innerHTML = "";
  for (const r of filtered) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" class="reg-check" data-email="${r.email}"></td>
      <td>${r.email}</td>
      <td>${r.at_len > 0 ? `<button class="copy-cell" data-email="${r.email}" data-field="access_token" title="点击复制 access_token">✅ ${r.at_len} 📋</button>` : "—"}</td>
      <td>${r.st_len > 0 ? `<button class="copy-cell" data-email="${r.email}" data-field="session_token" title="点击复制 session_token">✅ ${r.st_len} 📋</button>` : "—"}</td>
      <td>${r.rt_len > 0 ? `<button class="copy-cell" data-email="${r.email}" data-field="refresh_token" title="点击复制 refresh_token">✅ ${r.rt_len} 📋</button>` : "—"}</td>
      <td>${fmtTime(r.created_at)}</td>
      <td>
        <button data-act="view" data-email="${r.email}">查看凭证</button>
        <button data-act="del" data-email="${r.email}">删除</button>
      </td>
    `;
    tb.appendChild(tr);
  }
  $("#regSelectAll").checked = false;
  _updateSelCountReg();
}
$("#btnRefreshReg").addEventListener("click", refreshRegistered);

// radio 切换时自动刷新
document.querySelectorAll("input[name='regFilter']").forEach(r => {
  r.addEventListener("change", refreshRegistered);
});

// ── 注册结果：复选框 + 批量删 + 单行删 ──

function _selectedRegEmails() {
  return Array.from(document.querySelectorAll(".reg-check:checked")).map(c => c.dataset.email);
}
function _updateSelCountReg() {
  const n = _selectedRegEmails().length;
  $("#selCountReg").textContent = n;
  $("#btnDeleteSelectedReg").disabled = n === 0;
}
$("#regTable").addEventListener("change", (e) => {
  if (e.target.classList.contains("reg-check")) _updateSelCountReg();
});
$("#regSelectAll").addEventListener("change", (e) => {
  document.querySelectorAll(".reg-check").forEach(c => c.checked = e.target.checked);
  _updateSelCountReg();
});

$("#btnDeleteSelectedReg").addEventListener("click", async () => {
  const emails = _selectedRegEmails();
  if (!emails.length) return;
  if (!confirm(`确定删除选中的 ${emails.length} 条凭证？(不可恢复)`)) return;
  $("#exportResult").textContent = "删除中...";
  $("#exportResult").className = "result";
  try {
    const r = await api("/api/registered/bulk_delete", {
      method: "POST",
      body: JSON.stringify({ emails }),
    });
    $("#exportResult").textContent = `✅ 已删除 ${r.deleted} 条凭证`;
    $("#exportResult").className = "result ok";
    refreshRegistered();
  } catch (e) {
    $("#exportResult").textContent = "❌ " + e.message;
    $("#exportResult").className = "result bad";
  }
});

$("#btnDeleteAllReg").addEventListener("click", async () => {
  if (!confirm("⚠️ 这会清空注册结果表里的所有凭证！\n确定继续？（号池不受影响）")) return;
  if (!confirm("再次确认：真的要删除全部凭证吗？此操作不可恢复！")) return;
  $("#exportResult").textContent = "清空中...";
  $("#exportResult").className = "result";
  try {
    const r = await api("/api/registered/bulk_delete", {
      method: "POST",
      body: JSON.stringify({ all: true }),
    });
    $("#exportResult").textContent = `✅ 已清空 ${r.deleted} 条凭证`;
    $("#exportResult").className = "result ok";
    refreshRegistered();
  } catch (e) {
    $("#exportResult").textContent = "❌ " + e.message;
    $("#exportResult").className = "result bad";
  }
});

// 缓存最近查看的凭证（用于"复制全部 JSON"按钮和单字段复制）
let _credCache = null;

async function _loadCred(email) {
  if (_credCache && _credCache.email === email) return _credCache;
  const { data } = await api(`/api/registered/${encodeURIComponent(email)}`);
  _credCache = data;
  return data;
}

async function _copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    if (btn) {
      const orig = btn.textContent;
      const cls = btn.className;
      btn.textContent = "✅ 已复制";
      btn.className = cls + " copied";
      setTimeout(() => { btn.textContent = orig; btn.className = cls; }, 1200);
    }
  } catch (e) {
    alert("复制失败: " + e.message);
  }
}

$("#regTable").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  const email = btn.dataset.email;
  if (!email) return;

  // 行内快捷复制（access/session/refresh 列直接点）
  if (btn.classList.contains("copy-cell")) {
    const field = btn.dataset.field;
    try {
      const cred = await _loadCred(email);
      const val = cred[field] || "";
      if (!val) { alert(`${field} 为空`); return; }
      await _copyText(val, btn);
    } catch (err) { alert("加载凭证失败: " + err.message); }
    return;
  }

  // 「查看凭证」打开模态框
  if (btn.dataset.act === "view") {
    try {
      const cred = await _loadCred(email);
      _renderCredModal(email, cred);
    } catch (err) { alert("加载凭证失败: " + err.message); }
  }

  // 「删除」单行删
  if (btn.dataset.act === "del") {
    if (!confirm(`删除 ${email} 的凭证？`)) return;
    try {
      await api(`/api/registered/${encodeURIComponent(email)}`, { method: "DELETE" });
      refreshRegistered();
    } catch (err) { alert("删除失败: " + err.message); }
  }
});


function _renderCredModal(email, cred) {
  $("#credTitle").textContent = email;
  const box = $("#credFields");
  box.innerHTML = "";

  // 主要凭证按顺序展示，每项独立复制按钮
  const KEYS = [
    ["access_token",  "access_token"],
    ["session_token", "session_token"],
    ["refresh_token", "refresh_token"],
    ["id_token",      "id_token"],
    ["device_id",     "device_id"],
    ["csrf_token",    "csrf_token"],
    ["cookie_header", "cookie_header"],
    ["password",      "password"],
  ];
  for (const [key, label] of KEYS) {
    const val = cred[key] || "";
    if (!val) continue;
    const row = document.createElement("div");
    row.className = "cred-row";
    row.innerHTML = `
      <div class="cred-row-head">
        <span class="cred-label">${label}</span>
        <span class="cred-meta">len=${val.length}</span>
        <button class="cred-copy" data-val-key="${key}">📋 复制</button>
      </div>
      <pre class="cred-val">${escapeHtml(val)}</pre>
    `;
    box.appendChild(row);
  }

  // extra（含 cookie 同步等其他元数据）
  if (cred.extra && Object.keys(cred.extra).length > 0) {
    const row = document.createElement("div");
    row.className = "cred-row";
    row.innerHTML = `
      <div class="cred-row-head">
        <span class="cred-label">extra</span>
        <span class="cred-meta">${Object.keys(cred.extra).length} keys</span>
        <button class="cred-copy" data-val-key="__extra__">📋 复制 JSON</button>
      </div>
      <pre class="cred-val">${escapeHtml(JSON.stringify(cred.extra, null, 2))}</pre>
    `;
    box.appendChild(row);
  }

  $("#credModal").classList.remove("hidden");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// 模态框内单字段复制
$("#credFields").addEventListener("click", async (e) => {
  const btn = e.target.closest("button.cred-copy");
  if (!btn) return;
  const key = btn.dataset.valKey;
  const val = key === "__extra__"
    ? JSON.stringify(_credCache.extra, null, 2)
    : (_credCache[key] || "");
  await _copyText(val, btn);
});

$("#credClose").addEventListener("click", () => {
  $("#credModal").classList.add("hidden");
});
$("#credCopyJson").addEventListener("click", async (e) => {
  if (!_credCache) return;
  await _copyText(JSON.stringify(_credCache, null, 2), e.currentTarget);
});

// ──────────────────────── 运行记录 ────────────────────────

async function refreshRuns() {
  const { items } = await api("/api/runs");
  const tb = $("#runTable tbody");
  tb.innerHTML = "";
  for (const r of items) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><code>${r.run_id}</code></td>
      <td>${r.email}</td>
      <td><span class="status ${r.status === 'done' ? 'done' : r.status === 'failed' ? 'failed' : r.status === 'stopped' ? 'stopped' : 'running'}">${r.status}</span></td>
      <td>${fmtTime(r.started_at)}</td>
      <td title="${r.error || ''}">${(r.error || '').slice(0, 60)}</td>
    `;
    tb.appendChild(tr);
  }
}
$("#btnRefreshRuns").addEventListener("click", refreshRuns);

// ──────────────────────── 🤖 Auto-Loop 全自动批量 ────────────────────────

const AUTO_BTNS = {
  start:  $("#btnAutoStart"),
  pause:  $("#btnAutoPause"),
  resume: $("#btnAutoResume"),
  stop:   $("#btnAutoStop"),
};

function _autoOptions() {
  return {
    proxy: $("#regProxy").value.trim(),
    proxy_pool: $("#autoProxyPool").value,
    concurrency: parseInt($("#autoConcurrency").value || "1", 10),
    otp_timeout: parseInt($("#regOtpTimeout").value || "180", 10),
    want_access_token: true,
    want_session_token: true,
    want_refresh_token: true,
    cool_down_seconds: parseFloat($("#autoCoolDown").value || "3") || 0,
  };
}

async function autoStart() {
  try {
    await api("/api/auto/start", { method: "POST", body: JSON.stringify(_autoOptions()) });
  } catch (e) { alert("启动失败: " + e.message); }
}
async function autoCall(path) {
  try { await api(path, { method: "POST" }); }
  catch (e) { alert(`${path} 失败: ${e.message}`); }
}
AUTO_BTNS.start.addEventListener("click", autoStart);
AUTO_BTNS.pause.addEventListener("click", () => autoCall("/api/auto/pause"));
AUTO_BTNS.resume.addEventListener("click", () => autoCall("/api/auto/resume"));
AUTO_BTNS.stop.addEventListener("click", () => autoCall("/api/auto/stop"));

function _renderAutoStatus(s) {
  const stateLabel = {
    "stopped": "未运行",
    "running": "运行中",
    "paused":  "已暂停",
  }[s.state] || s.state;
  const elapsed = s.elapsed ? Math.round(s.elapsed) + "s" : "—";
  const workers = Array.isArray(s.workers) ? s.workers : [];
  const workerRows = workers.length
    ? workers.map(w => {
        const dur = w.started_at ? Math.round(Date.now() / 1000 - w.started_at) + "s" : "";
        const px = w.proxy ? ` [${escapeHtml(w.proxy.slice(0, 30))}${w.proxy.length > 30 ? "..." : ""}]` : "";
        return `<div class="auto-worker"><b>W${w.id}</b><code>${escapeHtml(w.email)}</code><span>${dur}${px}</span></div>`;
      }).join("")
    : "";
  const meta = `并发=${s.concurrency || 1}` + (s.proxy_pool_size ? ` 代理池=${s.proxy_pool_size}` : "");
  const ok = Number(s.registered_ok || 0);
  const fail = Number(s.registered_fail || 0);
  const done = ok + fail;
  const total = Number(s.total || s.pool_total || 0);
  const denom = total > 0 ? total : done;
  const pct = denom > 0 ? Math.min(100, Math.round(done / denom * 100)) : 0;
  const lastMessage = String(s.last_message || "").trim();
  const stateNote = lastMessage || (s.state === "stopped" && done > 0 ? `已停止（成功 ${ok} / 失败 ${fail}）` : "");
  $("#autoBatchSummary").textContent = `本批次已完成 ${ok} / 失败 ${fail}`;
  $("#autoProgressBar").style.width = `${pct}%`;
  $("#autoProgressText").textContent = `${done} / ${denom || 0} 完成 · ${pct}%`;
  $("#autoStatus").innerHTML = `
    <span class="auto-status-line">
      <b class="${s.state === "running" ? "ok" : s.state === "paused" ? "warn" : ""}">${stateLabel}</b>
      ${stateNote ? `&nbsp;|&nbsp;<span class="auto-msg">${escapeHtml(stateNote)}</span>` : ""}
      &nbsp;|&nbsp; 运行: ${elapsed}
      &nbsp;|&nbsp; <span class="auto-meta">${meta}</span>
    </span>
    ${workerRows ? "<br>" + workerRows : ""}
  `;
  // 按钮可用性
  const st = s.state;
  AUTO_BTNS.start.disabled  = (st === "running" || st === "paused");
  AUTO_BTNS.pause.disabled  = (st !== "running");
  AUTO_BTNS.resume.disabled = (st !== "paused");
  AUTO_BTNS.stop.disabled   = (st === "stopped");
}

let _autoEs = null;
function _connectAutoStream() {
  if (_autoEs) { try { _autoEs.close(); } catch (_) {} }
  const es = new EventSource("/api/auto/stream");
  _autoEs = es;
  es.addEventListener("state", (e) => {
    try { _renderAutoStatus(JSON.parse(e.data)); } catch (_) {}
  });
  es.addEventListener("run_started", (e) => {
    try {
      const d = JSON.parse(e.data);
      logLine(`[auto] ▶ 开始注册 ${d.email} (run=${d.run_id})`, "evt");
      // 复用单跑的 SSE 流，自动接管日志框 + 状态栏复制按钮
      streamRun(d.run_id);
    } catch (_) {}
  });
  es.addEventListener("run_finished", (e) => {
    try {
      const d = JSON.parse(e.data);
      const tag = d.ok ? "✅" : (d.category === "network" ? "🌐 网络错误（号已 release）" : "❌");
      logLine(`[auto] ${tag} ${d.email} 完成`, d.ok ? "ok" : "err");
    } catch (_) {}
  });
  es.addEventListener("circuit_break", (e) => {
    try {
      const d = JSON.parse(e.data);
      logLine(`[auto] ⚠️ 熔断: ${d.reason}`, "err");
      _showBanner(d.reason);
    } catch (_) {}
  });
  es.onerror = () => {
    // 自动重连
    try { es.close(); } catch (_) {}
    _autoEs = null;
    setTimeout(_connectAutoStream, 2000);
  };
}

// 顶部红色告警横幅
function _showBanner(msg) {
  const b = $("#alertBanner");
  $("#alertBannerMsg").textContent = msg;
  b.classList.remove("hidden");
}
$("#alertBannerClose").addEventListener("click", () => {
  $("#alertBanner").classList.add("hidden");
});

// ──────────────────────── 表单持久化（localStorage 自动保存/恢复）────────────────────────

const FORM_KEY = "gpt_outlook_register_form_v1";

// id -> 类型（默认 text；checkbox 走 .checked）
const PERSIST_FIELDS = {
  regProxy:        "text",
  regOtpTimeout:   "text",
  autoCoolDown:    "text",
  autoConcurrency: "text",
  autoProxyPool:   "text",
};

function _saveForm() {
  const data = {};
  for (const [id, kind] of Object.entries(PERSIST_FIELDS)) {
    const el = document.getElementById(id);
    if (!el) continue;
    data[id] = kind === "check" ? !!el.checked : (el.value || "");
  }
  try { localStorage.setItem(FORM_KEY, JSON.stringify(data)); } catch (_) {}
}

function _loadForm() {
  let data = {};
  try { data = JSON.parse(localStorage.getItem(FORM_KEY) || "{}"); } catch (_) { data = {}; }
  for (const [id, kind] of Object.entries(PERSIST_FIELDS)) {
    if (!(id in data)) continue;
    const el = document.getElementById(id);
    if (!el) continue;
    if (kind === "check") el.checked = !!data[id];
    else el.value = data[id] || "";
  }
}

// 绑定 input/change 自动保存
function _bindAutoSave() {
  for (const id of Object.keys(PERSIST_FIELDS)) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.addEventListener("input", _saveForm);
    el.addEventListener("change", _saveForm);
  }
}

// ──────────────────────── 📧 邮箱配置 ────────────────────────

function _syncCfFields(source) {
  const isCf = source === "cf_temp";
  $("#cfTempCfg").classList.toggle("hidden", !isCf);
  $("#outlookMailCfg").classList.toggle("hidden", isCf);
  $("#btnTestMail").classList.toggle("hidden", !isCf);
}

async function loadMailConfig() {
  try {
    const { config } = await api("/api/settings/mail");
    const src = config.mail_source || "outlook";
    $("#mailSourceSelect").value = src;
    _syncCfFields(src);
    $("#cfApiUrl").value = config.cf_api_url || "";
    $("#cfDomain").value = config.cf_domain || "";
    $("#cfAdminToken").value = config.cf_admin_token || "";
    $("#cfEnablePrefix").checked = config.cf_enable_prefix !== "0";
    $("#cfAdminToken").placeholder = "Worker 配置的 ADMIN_PASSWORDS";
  } catch (e) {
    console.error("loadMailConfig:", e);
  }
}

$("#mailSourceSelect").addEventListener("change", (e) => {
  _syncCfFields(e.target.value);
});

$("#btnTestMail").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = "⏳ 测试中...";
  $("#mailCfgResult").textContent = "";
  try {
    const r = await api("/api/settings/mail/test", { method: "POST" });
    $("#mailCfgResult").textContent = "✅ " + r.message;
    $("#mailCfgResult").className = "result ok";
  } catch (err) {
    $("#mailCfgResult").textContent = "❌ " + err.message;
    $("#mailCfgResult").className = "result bad";
  } finally {
    btn.disabled = false;
    btn.textContent = "🔌 测试 CF 连通性";
  }
});

// ──────────────────────── 📱 SMS 接码配置 ────────────────────────

// 全量国家列表（id → name_cn + openai_sms_safe）；首次加载配置时从后端拿
let _smsAllCountries = [];
let _smsSafeCountrySet = new Set();

async function _loadSmsAllCountries() {
  if (_smsAllCountries.length) return _smsAllCountries;
  try {
    const r = await api("/api/settings/sms/all_countries");
    _smsAllCountries = r.countries || [];
    _smsSafeCountrySet = new Set(r.openai_sms_safe || []);
  } catch (e) {
    console.error("加载国家列表失败:", e);
  }
  return _smsAllCountries;
}

function _renderSmsCountrySelect(selectEl, currentValue) {
  selectEl.innerHTML = "";
  for (const c of _smsAllCountries) {
    const opt = document.createElement("option");
    opt.value = c.id;
    opt.textContent = `${c.id} - ${c.name_cn}`;
    selectEl.appendChild(opt);
  }
  if (currentValue) selectEl.value = currentValue;
}

function _renderSmsAllowedCountriesBox(checkedIds) {
  const box = $("#smsAllowedCountriesBox");
  box.innerHTML = "";
  const checkedSet = new Set((checkedIds || "").split(",").map(s => s.trim()).filter(Boolean));

  // 先渲染所有国家（带 data 属性用于搜索）
  for (const c of _smsAllCountries) {
    const lab = document.createElement("label");
    lab.className = "check country-item";
    lab.style.fontSize = "12px";
    lab.style.padding = "4px 6px";
    lab.style.lineHeight = "1.4";
    lab.dataset.countryId = c.id;
    lab.dataset.countryName = c.name_cn.toLowerCase();

    // 显示：ID·国家名 (价格/库存)
    const priceInfo = c.price != null && c.count != null
      ? ` <span style="color:#999;font-size:11px">(${c.price}/${c.count})</span>`
      : "";
    lab.innerHTML = `<input type="checkbox" value="${c.id}" ${checkedSet.has(c.id) ? "checked" : ""}>${c.id}·${c.name_cn}${priceInfo}`;
    box.appendChild(lab);
  }

  _updateAllowedCountryCount();
  box.querySelectorAll("input[type=checkbox]").forEach(cb => {
    cb.addEventListener("change", _updateAllowedCountryCount);
  });

  // 绑定搜索框
  const searchInput = $("#smsCountrySearch");
  if (searchInput && !searchInput.dataset.bound) {
    searchInput.dataset.bound = "1";
    searchInput.addEventListener("input", (e) => {
      const query = e.target.value.toLowerCase().trim();
      box.querySelectorAll(".country-item").forEach(lab => {
        const id = lab.dataset.countryId || "";
        const name = lab.dataset.countryName || "";
        const match = !query || id.includes(query) || name.includes(query);
        lab.style.display = match ? "" : "none";
      });
    });
  }
}

function _syncCustomSmsFields(provider) {
  const isCustom = provider === "custom";
  $("#customSmsCfg").classList.toggle("hidden", !isCustom);
  $("#smsBowerCfg").classList.toggle("hidden", isCustom);
  $("#btnTestSms").classList.toggle("hidden", isCustom);
  $("#btnCustomSmsImport")?.classList.toggle("hidden", !isCustom);
  $(".custom-sms-regex-field")?.classList.toggle("hidden", !isCustom);
  $("#customSmsImportResult")?.classList.toggle("hidden", !isCustom);
  if (isCustom) loadCustomSmsPool();
}

function _shortApiUrl(url) {
  const s = String(url || "");
  if (s.length <= 42) return s;
  return `${s.slice(0, 24)}...${s.slice(-14)}`;
}

const CUSTOM_SMS_STATUS_LABELS = {
  available: "可用",
  in_use: "正在使用",
  done: "已完成",
  failed: "失败",
};

function _customSmsStatusLabel(status) {
  return CUSTOM_SMS_STATUS_LABELS[status] || status || "";
}

function _renderCustomSmsPool(items) {
  const body = $("#customSmsPoolBody");
  if (!body) return;
  body.innerHTML = "";

  if (!items || !items.length) {
    body.innerHTML = `<tr><td colspan="8" class="empty">暂无导入记录</td></tr>`;
    $("#customSmsSelectAll").checked = false;
    _updateCustomSmsSelCount();
    $("#customSmsPoolSummary").textContent = "可用 (0) / 正在使用 (0) / 已完成 (0) / 失败 (0)";
    $("#customSmsPoolSummary").className = "result";
    return;
  }

  const counts = { available: 0, in_use: 0, done: 0, failed: 0 };
  for (const item of items) {
    const status = String(item.status || "available");
    if (Object.prototype.hasOwnProperty.call(counts, status)) counts[status] += 1;
    const statusClass = Object.prototype.hasOwnProperty.call(counts, status) ? status : "";
    const apiUrl = item.api_url || "";
    const failReason = item.fail_reason || "";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" class="custom-sms-check" data-phone="${escapeHtml(item.phone || "")}"></td>
      <td>${escapeHtml(item.phone || "")}</td>
      <td><span class="status ${statusClass}">${escapeHtml(_customSmsStatusLabel(status))}</span></td>
      <td>${Number(item.success_count || 0)}</td>
      <td><code class="sms-api-url" title="${escapeHtml(apiUrl)}">${escapeHtml(_shortApiUrl(apiUrl))}</code></td>
      <td>${fmtTime(item.imported_at)}</td>
      <td title="${escapeHtml(failReason)}">${escapeHtml(failReason.slice(0, 48))}</td>
      <td class="custom-sms-actions">
        <button data-act="reset-custom-sms" data-phone="${escapeHtml(item.phone || "")}" title="重置为 available">重置</button>
        <button data-act="delete-custom-sms" data-phone="${escapeHtml(item.phone || "")}" title="删除该手机号">删除</button>
      </td>
    `;
    body.appendChild(tr);
  }

  $("#customSmsPoolSummary").textContent =
    `可用 (${counts.available}) / 正在使用 (${counts.in_use}) / 已完成 (${counts.done}) / 失败 (${counts.failed})`;
  $("#customSmsPoolSummary").className = "result ok";
  $("#customSmsSelectAll").checked = false;
  _updateCustomSmsSelCount();
}

function _selectedCustomSmsPhones() {
  return Array.from(document.querySelectorAll(".custom-sms-check:checked"))
    .map(c => c.dataset.phone)
    .filter(Boolean);
}

function _updateCustomSmsSelCount() {
  const el = $("#customSmsSelCount");
  if (!el) return;
  el.textContent = _selectedCustomSmsPhones().length;
}

async function loadCustomSmsPool() {
  const body = $("#customSmsPoolBody");
  if (!body) return;
  $("#customSmsPoolSummary").textContent = "加载中...";
  $("#customSmsPoolSummary").className = "result";
  try {
    const r = await api("/api/settings/sms/custom/accounts?limit=500");
    _renderCustomSmsPool(r.items || []);
  } catch (e) {
    $("#customSmsPoolSummary").textContent = "❌ " + e.message;
    $("#customSmsPoolSummary").className = "result bad";
    body.innerHTML = `<tr><td colspan="8" class="empty bad">加载失败</td></tr>`;
    $("#customSmsSelectAll").checked = false;
    _updateCustomSmsSelCount();
  }
}

$("#customSmsPoolTable").addEventListener("change", (e) => {
  if (e.target.classList.contains("custom-sms-check")) _updateCustomSmsSelCount();
});

$("#customSmsSelectAll").addEventListener("change", (e) => {
  document.querySelectorAll(".custom-sms-check").forEach(c => {
    c.checked = e.target.checked;
  });
  _updateCustomSmsSelCount();
});

$("#btnResetAllCustomSms").addEventListener("click", async (e) => {
  if (!confirm("把所有手机号状态重置为 available？\n不会清空使用次数。")) return;
  const btn = e.currentTarget;
  btn.disabled = true;
  $("#customSmsPoolSummary").textContent = "全部重置中...";
  $("#customSmsPoolSummary").className = "result";
  try {
    const r = await api("/api/settings/sms/custom/accounts/reset_all", { method: "POST" });
    $("#customSmsPoolSummary").textContent = `✅ 已重置 ${r.reset} 个手机号`;
    $("#customSmsPoolSummary").className = "result ok";
    await loadCustomSmsPool();
  } catch (err) {
    $("#customSmsPoolSummary").textContent = "❌ 全部重置失败: " + err.message;
    $("#customSmsPoolSummary").className = "result bad";
  } finally {
    btn.disabled = false;
  }
});

$("#customSmsPoolTable").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  const phone = btn.dataset.phone || "";
  if (!phone) return;

  if (btn.dataset.act === "reset-custom-sms") {
    if (!confirm(`重置 ${phone} 为 available？`)) return;
    btn.disabled = true;
    try {
      await api(`/api/settings/sms/custom/accounts/${encodeURIComponent(phone)}/reset`, { method: "POST" });
      loadCustomSmsPool();
    } catch (err) {
      alert("重置失败: " + err.message);
      btn.disabled = false;
    }
  } else if (btn.dataset.act === "delete-custom-sms") {
    if (!confirm(`删除手机号 ${phone}？`)) return;
    btn.disabled = true;
    try {
      await api(`/api/settings/sms/custom/accounts/${encodeURIComponent(phone)}`, { method: "DELETE" });
      loadCustomSmsPool();
    } catch (err) {
      alert("删除失败: " + err.message);
      btn.disabled = false;
    }
  }
});

function _updateAllowedCountryCount() {
  const checked = $("#smsAllowedCountriesBox").querySelectorAll("input[type=checkbox]:checked");
  $("#smsAllowedCountryCount").textContent = `已选 ${checked.length} 个国家`;
}

function _getAllowedCountriesValue() {
  const checked = $("#smsAllowedCountriesBox").querySelectorAll("input[type=checkbox]:checked");
  return Array.from(checked).map(cb => cb.value).join(",");
}

async function loadSmsConfig() {
  await _loadSmsAllCountries();
  try {
    const { config } = await api("/api/settings/sms");
    $("#smsEnabled").checked = config.sms_enabled !== "0";
    const provider = config.sms_provider || "custom";
    $("#smsProviderSelect").value = provider;
    _syncCustomSmsFields(provider);
    $("#smsApiKey").value = "";
    $("#smsApiKey").placeholder = (config.sms_api_key === "***")
      ? "已设置（留空不修改）"
      : "粘贴接码平台 API Key";
    _renderSmsCountrySelect($("#smsCountry"), config.sms_country || "150");
    $("#smsService").value = config.sms_service || "dr";
    $("#smsMaxPrice").value = config.sms_max_price || "";
    $("#smsPhoneSuccessMax").value = config.sms_phone_success_max || "3";
    $("#smsReusePhone").checked = config.sms_reuse_phone === "1";
    $("#smsAutoCountry").checked = config.sms_auto_country === "1";
    $("#smsAutoMinStock").value = config.sms_auto_min_stock || "20";
    $("#smsAutoMaxPrice").value = config.sms_auto_max_price || "";
    _renderSmsAllowedCountriesBox(config.sms_allowed_countries || "");
    $("#smsMaxPhoneAttempts").value = config.sms_max_phone_attempts || "";
    $("#smsPerPhoneTimeout").value = config.sms_per_phone_timeout || "80";
    $("#btnTestSms").classList.toggle("hidden", provider === "custom");
    $("#smsCustomRegex").value = config.sms_custom_regex || "(?<!\\d)\\d{6}(?!\\d)";
  } catch (e) {
    console.error("loadSmsConfig:", e);
  }
}

$("#smsProviderSelect").addEventListener("change", (e) => {
  _syncCustomSmsFields(e.target.value);
});

$("#btnRefreshCustomSmsPool").addEventListener("click", loadCustomSmsPool);

document.querySelectorAll(".btnSaveMailCfg").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const source = $("#mailSourceSelect").value || "outlook";
    const isCf = source === "cf_temp";
    const body = {
      mail_source:    source,
    };
    if (isCf) {
      body.cf_api_url = $("#cfApiUrl").value.trim();
      body.cf_admin_token = $("#cfAdminToken").value.trim() || "***";
      body.cf_domain = $("#cfDomain").value.trim();
      body.cf_enable_prefix = $("#cfEnablePrefix").checked ? "1" : "0";
    }
    try {
      await api("/api/settings/mail", { method: "POST", body: JSON.stringify(body) });
      $("#mailCfgResult").textContent = "✅ 保存成功";
      $("#mailCfgResult").className = "result ok";
    } catch (e) {
      $("#mailCfgResult").textContent = "❌ " + e.message;
      $("#mailCfgResult").className = "result bad";
    }
    setTimeout(() => { $("#mailCfgResult").textContent = ""; }, 3000);
  });
});

$("#btnClearAllowedCountries")?.addEventListener("click", () => {
  $("#smsAllowedCountriesBox").querySelectorAll("input[type=checkbox]").forEach(cb => {
    cb.checked = false;
  });
  _updateAllowedCountryCount();
});

$("#btnSaveSmsCfg").addEventListener("click", async () => {
  const apiKeyInput = $("#smsApiKey").value.trim();
  const body = {
    sms_enabled:           $("#smsEnabled").checked ? "1" : "0",
    sms_provider:          $("#smsProviderSelect").value || "custom",
    sms_api_key:           apiKeyInput || "***",
    sms_country:           $("#smsCountry").value.trim() || "52",
    sms_service:           $("#smsService").value.trim() || "dr",
    sms_max_price:         $("#smsMaxPrice").value.trim(),
    sms_phone_success_max: $("#smsPhoneSuccessMax").value.trim() || "3",
    sms_reuse_phone:       $("#smsReusePhone").checked ? "1" : "0",
    sms_auto_country:      $("#smsAutoCountry").checked ? "1" : "0",
    sms_allowed_countries: _getAllowedCountriesValue(),
    sms_auto_min_stock:    $("#smsAutoMinStock").value.trim() || "20",
    sms_auto_max_price:    $("#smsAutoMaxPrice").value.trim(),
    sms_max_phone_attempts: $("#smsMaxPhoneAttempts").value.trim(),
    sms_per_phone_timeout: $("#smsPerPhoneTimeout").value.trim() || "80",
    sms_custom_regex:      $("#smsCustomRegex").value.trim() || "(?<!\\d)\\d{6}(?!\\d)",
  };
  if (body.sms_provider !== "custom") {
    delete body.sms_custom_regex;
  }
  if (body.sms_provider === "custom") {
    try {
      new RegExp(body.sms_custom_regex);
    } catch (e) {
      $("#smsCfgResult").textContent = "❌ 自定义正则无效: " + e.message;
      $("#smsCfgResult").className = "result bad";
      return;
    }
  }
  try {
    await api("/api/settings/sms", { method: "POST", body: JSON.stringify(body) });
    $("#smsCfgResult").textContent = "✅ 保存成功";
    $("#smsCfgResult").className = "result ok";
    setTimeout(loadSmsConfig, 300);
  } catch (e) {
    $("#smsCfgResult").textContent = "❌ " + e.message;
    $("#smsCfgResult").className = "result bad";
  }
  setTimeout(() => { $("#smsCfgResult").textContent = ""; }, 3500);
});

$("#btnCustomSmsImport").addEventListener("click", async () => {
  const text = $("#customSmsPhoneText").value.trim();
  if (!text) {
    $("#customSmsImportResult").textContent = "请输入自定义接码内容";
    return;
  }
  try {
    const r = await api("/api/settings/sms/custom/import", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    $("#customSmsImportResult").textContent =
      `✅ 解析 ${r.parsed} 行，新增 ${r.inserted}，更新 ${r.updated}，跳过 ${r.skipped}`;
    $("#customSmsImportResult").className = "result ok";
    $("#customSmsPhoneText").value = "";
    loadCustomSmsPool();
  } catch (e) {
    $("#customSmsImportResult").textContent = "❌ " + e.message;
    $("#customSmsImportResult").className = "result bad";
  }
});

async function _manualExportSelected(targets) {
  const emails = _selectedRegEmails();
  if (!emails.length) {
    alert("请先勾选要导出的凭证");
    return;
  }
  $("#exportResult").textContent = "导出中...";
  $("#exportResult").className = "result";
  try {
    const r = await api("/api/registered/export_to_panel", {
      method: "POST",
      body: JSON.stringify({ emails, targets }),
    });
    $("#exportResult").textContent = `✅ 已导出 ${r.results?.length || emails.length} 条`;
    $("#exportResult").className = "result ok";
  } catch (e) {
    $("#exportResult").textContent = "❌ " + e.message;
    $("#exportResult").className = "result bad";
  }
}

$("#btnExportCpa").addEventListener("click", () => _manualExportSelected(["cpa"]));
$("#btnExportSub2api").addEventListener("click", () => _manualExportSelected(["sub2api"]));

$("#btnTestSms").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = "⏳ 测试中...";
  $("#smsCfgResult").textContent = "";
  try {
    const r = await api("/api/settings/sms/test", { method: "POST" });
    $("#smsCfgResult").textContent = "✅ " + r.message;
    $("#smsCfgResult").className = "result ok";
  } catch (err) {
    $("#smsCfgResult").textContent = "❌ " + err.message;
    $("#smsCfgResult").className = "result bad";
  } finally {
    btn.disabled = false;
    btn.textContent = "🔌 测试余额";
  }
});

// ──────────────────────── 📤 自动导出配置 (CPA / SUB2API) ────────────────────────

async function loadExportConfig() {
  try {
    const { config } = await api("/api/settings/export");
    window.__exportCfg = config;
    // CPA
    $("#cpaEnabled").checked = config.cpa_enabled === "1";
    $("#cpaUrl").value = config.cpa_url || "";
    $("#cpaMgmtKey").value = "";
    $("#cpaMgmtKey").placeholder = config.cpa_mgmt_key === "***"
      ? "已设置（留空不修改）"
      : "粘贴 CPA 管理密钥";
    $("#cpaTimeout").value = config.cpa_timeout || "30";
    // SUB2API
    $("#sub2apiEnabled").checked = config.sub2api_enabled === "1";
    $("#sub2apiUrl").value = config.sub2api_url || "";
    $("#sub2apiApiKey").value = "";
    $("#sub2apiApiKey").placeholder = config.sub2api_api_key === "***"
      ? "已设置（留空不修改）"
      : "粘贴面板里生成的 x-api-key";
    $("#sub2apiGroupIds").value = config.sub2api_group_ids || "2";
    $("#sub2apiTimeout").value = config.sub2api_timeout || "30";
    $("#btnExportCpa").disabled = !(config.cpa_enabled === "1");
    $("#btnExportSub2api").disabled = !(config.sub2api_enabled === "1");
  } catch (e) {
    console.error("loadExportConfig:", e);
  }
}

$("#btnSaveExportCfg").addEventListener("click", async () => {
  const cpaKeyInput = $("#cpaMgmtKey").value.trim();
  const sub2apiKeyInput = $("#sub2apiApiKey").value.trim();
  const body = {
    // CPA
    cpa_enabled:  $("#cpaEnabled").checked ? "1" : "0",
    cpa_url:      $("#cpaUrl").value.trim(),
    cpa_mgmt_key: cpaKeyInput || "***",
    cpa_timeout:  $("#cpaTimeout").value.trim() || "30",
    // SUB2API
    sub2api_enabled:    $("#sub2apiEnabled").checked ? "1" : "0",
    sub2api_url:        $("#sub2apiUrl").value.trim(),
    sub2api_api_key:    sub2apiKeyInput || "***",
    sub2api_group_ids:  $("#sub2apiGroupIds").value.trim() || "2",
    sub2api_timeout:    $("#sub2apiTimeout").value.trim() || "30",
  };
  try {
    await api("/api/settings/export", { method: "POST", body: JSON.stringify(body) });
    $("#exportCfgResult").textContent = "✅ 保存成功";
    $("#exportCfgResult").className = "result ok";
    setTimeout(loadExportConfig, 300);
  } catch (e) {
    $("#exportCfgResult").textContent = "❌ " + e.message;
    $("#exportCfgResult").className = "result bad";
  }
  setTimeout(() => { $("#exportCfgResult").textContent = ""; }, 3500);
});

async function _testExportTarget(target, btn, resultEl, origText) {
  btn.disabled = true;
  btn.textContent = "⏳ 测试中...";
  resultEl.textContent = "";
  try {
    const r = await api("/api/settings/export/test", {
      method: "POST",
      body: JSON.stringify({ target }),
    });
    resultEl.textContent = "✅ " + (r.message || "连通正常");
    resultEl.className = "result ok";
  } catch (e) {
    resultEl.textContent = "❌ " + e.message;
    resultEl.className = "result bad";
  } finally {
    btn.disabled = false;
    btn.textContent = origText;
  }
}

$("#btnTestCpa").addEventListener("click", (e) => {
  _testExportTarget("cpa", e.currentTarget, $("#cpaTestResult"), "🔌 测试 CPA 连通性");
});
$("#btnTestSub2api").addEventListener("click", (e) => {
  _testExportTarget("sub2api", e.currentTarget, $("#sub2apiTestResult"), "🔌 测试 SUB2API 连通性");
});

// ──────────────────────── 悬浮日志窗 ────────────────────────

function setupLogWindow() {
  const logwin = $("#logwin");
  const fab = $("#logFab");
  if (!logwin || !fab) return;

  const openLog = () => {
    logwin.classList.remove("hidden");
    if (window.innerWidth > 820) logwin.classList.remove("minimized");
    fab.classList.add("hidden");
  };

  const toggleLog = () => {
    if (logwin.classList.contains("hidden")) {
      openLog();
      return;
    }
    logwin.classList.toggle("minimized");
  };

  $("#logMin")?.addEventListener("click", () => {
    logwin.classList.toggle("minimized");
  });
  $("#logClose")?.addEventListener("click", () => {
    logwin.classList.add("hidden");
    fab.classList.remove("hidden");
  });
  $("#navLogToggle")?.addEventListener("click", toggleLog);
  $("#topLogToggle")?.addEventListener("click", toggleLog);
  fab.addEventListener("click", openLog);

  const syncCompactLog = () => {
    if (window.innerWidth <= 820) logwin.classList.add("minimized");
  };
  syncCompactLog();
  window.addEventListener("resize", syncCompactLog);

  const head = $("#logwinHead");
  if (head) {
    let dragging = false;
    let sx = 0;
    let sy = 0;
    let ox = 0;
    let oy = 0;

    head.addEventListener("mousedown", (e) => {
      if (e.target.closest(".logwin-tools")) return;
      dragging = true;
      sx = e.clientX;
      sy = e.clientY;
      const rect = logwin.getBoundingClientRect();
      ox = rect.left;
      oy = rect.top;
      logwin.style.left = `${ox}px`;
      logwin.style.top = `${oy}px`;
      logwin.style.right = "auto";
      logwin.style.bottom = "auto";
      document.body.style.userSelect = "none";
    });

    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const rect = logwin.getBoundingClientRect();
      const nextLeft = Math.max(4, Math.min(ox + e.clientX - sx, window.innerWidth - 60));
      const nextTop = Math.max(4, Math.min(oy + e.clientY - sy, window.innerHeight - 40));
      logwin.style.left = `${nextLeft}px`;
      logwin.style.top = `${nextTop}px`;
      logwin.style.width = `${rect.width}px`;
    });

    window.addEventListener("mouseup", () => {
      if (!dragging) return;
      dragging = false;
      document.body.style.userSelect = "";
    });
  }

  const resizeHandle = $("#logResize");
  if (resizeHandle) {
    let resizing = false;
    let sx = 0;
    let sy = 0;
    let sw = 0;
    let sh = 0;

    resizeHandle.addEventListener("mousedown", (e) => {
      resizing = true;
      e.preventDefault();
      sx = e.clientX;
      sy = e.clientY;
      const rect = logwin.getBoundingClientRect();
      sw = rect.width;
      sh = rect.height;
      logwin.style.left = `${rect.left}px`;
      logwin.style.top = `${rect.top}px`;
      logwin.style.right = "auto";
      logwin.style.bottom = "auto";
      document.body.style.userSelect = "none";
    });

    window.addEventListener("mousemove", (e) => {
      if (!resizing) return;
      logwin.style.width = `${Math.max(320, sw + e.clientX - sx)}px`;
      logwin.style.height = `${Math.max(148, sh + e.clientY - sy)}px`;
    });

    window.addEventListener("mouseup", () => {
      if (!resizing) return;
      resizing = false;
      document.body.style.userSelect = "";
    });
  }
}

// ──────────────────────── 启动 ────────────────────────

_loadForm();
_bindAutoSave();
$("#smsEnabled").checked = true;
$("#smsProviderSelect").value = "custom";
_syncCustomSmsFields("custom");
activateTab("register");
setupLogWindow();
refreshStats();
refreshPool();
_connectAutoStream();
setInterval(refreshStats, 5000);
