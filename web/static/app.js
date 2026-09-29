const token = document.querySelector('meta[name="htu-token"]').content;
const byId = (id) => document.getElementById(id);

const ui = {
  connectionPill: byId("connectionPill"),
  connectionText: byId("connectionText"),
  lastUpdate: byId("lastUpdate"),
  refreshButton: byId("refreshButton"),
  taskState: byId("taskState"),
  taskHint: byId("taskHint"),
  networkState: byId("networkState"),
  networkHint: byId("networkHint"),
  processState: byId("processState"),
  processHint: byId("processHint"),
  nextRun: byId("nextRun"),
  lastRun: byId("lastRun"),
  processIds: byId("processIds"),
  restartPolicy: byId("restartPolicy"),
  watchdogInterval: byId("watchdogInterval"),
  autoStartStatus: byId("autoStartStatus"),
  accountInput: byId("accountInput"),
  operatorSelect: byId("operatorSelect"),
  passwordInput: byId("passwordInput"),
  portalInput: byId("portalInput"),
  detectPortalButton: byId("detectPortalButton"),
  intervalInput: byId("intervalInput"),
  intervalDown: byId("intervalDown"),
  intervalUp: byId("intervalUp"),
  watchdogIntervalInput: byId("watchdogIntervalInput"),
  restartCountInput: byId("restartCountInput"),
  restartIntervalInput: byId("restartIntervalInput"),
  autoStartInput: byId("autoStartInput"),
  passwordConfigured: byId("passwordConfigured"),
  configForm: byId("configForm"),
  autoRefresh: byId("autoRefresh"),
  logTail: byId("logTail"),
  logOutput: byId("logOutput"),
  logMeta: byId("logMeta"),
  downloadLogButton: byId("downloadLogButton"),
  toast: byId("toast"),
};

const state = {
  statusLoading: false,
  logsLoading: false,
  actionLoading: false,
  taskConfigured: false,
  configInitialized: false,
  configDirty: false,
};

const operatorLabels = {
  yd: "中国移动",
  lt: "中国联通",
  dx: "中国电信",
  hsd: "校园本地账号",
};

function setConnection(kind, text) {
  ui.connectionPill.className = `status-pill ${kind}`;
  ui.connectionText.textContent = text;
}

function showToast(message, isError = false) {
  ui.toast.textContent = message;
  ui.toast.classList.toggle("error", isError);
  ui.toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => ui.toast.classList.remove("show"), 4200);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-HTU-Token", token);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json; charset=utf-8");
  }
  const response = await fetch(path, { ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  let payload;
  if (contentType.includes("application/json")) {
    payload = await response.json();
  } else {
    payload = { ok: response.ok, message: await response.text() };
  }
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `请求失败：HTTP ${response.status}`);
  }
  return payload;
}

function formatDate(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function formatTaskState(task) {
  const labels = {
    Running: "运行中",
    Ready: "已就绪",
    Disabled: "已禁用",
    Queued: "排队中",
    NotInstalled: "未配置",
  };
  return labels[task.state] || task.state || "未知";
}

function formatTaskResult(value) {
  if (value === 267009) return "运行中";
  if (value === 0) return "上次运行成功";
  if (!value) return "暂无运行记录";
  return `上次结果 0x${Number(value).toString(16).toUpperCase()}`;
}

function formatDuration(value) {
  if (!value) return "--";
  const match = String(value).match(/^P(?:([0-9]+)D)?T?(?:([0-9]+)H)?(?:([0-9]+)M)?$/);
  if (!match) return String(value);
  const parts = [];
  if (match[1]) parts.push(`${match[1]} 天`);
  if (match[2]) parts.push(`${match[2]} 小时`);
  if (match[3]) parts.push(`${match[3]} 分钟`);
  return parts.join(" ") || "--";
}

function updateStatus(data) {
  const task = data.task || {};
  const network = data.network || {};
  const config = data.config || {};
  const taskRunning = task.state === "Running";
  const watcherRunning = Number(task.watcherCount || 0) > 0;
  state.taskConfigured = task.state !== "NotInstalled";
  setActionState(state.actionLoading);

  ui.taskState.textContent = formatTaskState(task);
  ui.taskHint.textContent = task.error || formatTaskResult(task.lastTaskResult);
  ui.taskState.style.color = taskRunning ? "var(--success)" : task.ok === false ? "var(--danger)" : "var(--warning)";

  ui.networkState.textContent = network.online ? "在线" : "未认证 / 离线";
  ui.networkState.style.color = network.online ? "var(--success)" : "var(--danger)";
  ui.networkHint.textContent = network.online ? network.probe : (network.errors?.[0] || "等待自动登录");

  ui.processState.textContent = watcherRunning ? `${task.watcherCount} 个` : "未运行";
  ui.processState.style.color = watcherRunning ? "var(--success)" : "var(--danger)";
  ui.processHint.textContent = watcherRunning
    ? "后台常驻正常"
    : task.state === "Disabled"
      ? "任务和看门狗已停止"
      : task.state === "NotInstalled"
        ? "请先保存账号配置"
      : "等待看门狗拉起";

  ui.nextRun.textContent = task.state === "Disabled" ? "--" : formatDate(task.nextRunTime);
  ui.lastRun.textContent = `上次运行 ${formatDate(task.lastRunTime)}`;
  ui.processIds.textContent = task.processIds?.length ? task.processIds.join(", ") : "--";
  ui.restartPolicy.textContent = Number(task.restartCount) > 0
    ? `${task.restartCount} 次 / 每 ${formatDuration(task.restartInterval)}`
    : "已关闭";
  ui.watchdogInterval.textContent = formatDuration(task.repeatInterval);
  ui.autoStartStatus.textContent = task.autoStart ? "已开启" : "已关闭";
  ui.lastUpdate.textContent = `更新于 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;

  if (task.ok === false) {
    setConnection("danger", "任务不可读");
  } else if (task.state === "NotInstalled") {
    setConnection("neutral", "等待配置");
  } else if (taskRunning && watcherRunning) {
    setConnection("success", "后台正常");
  } else {
    setConnection("warning", "需要处理");
  }

  if (!state.configInitialized) {
    ui.accountInput.value = config.account || "";
    ui.operatorSelect.value = config.operator || "lt";
    ui.portalInput.value = config.portalUrl || "";
    ui.intervalInput.value = config.intervalSeconds || 10;
    ui.watchdogIntervalInput.value = config.watchdogIntervalMinutes ?? 5;
    ui.restartCountInput.value = config.restartCount ?? 999;
    ui.restartIntervalInput.value = config.restartIntervalMinutes ?? 1;
    ui.autoStartInput.checked = config.autoStart !== false;
    state.configInitialized = true;
  } else if (!state.configDirty) {
    ui.accountInput.value = config.account || ui.accountInput.value;
    ui.operatorSelect.value = config.operator || ui.operatorSelect.value;
    ui.portalInput.value = config.portalUrl || ui.portalInput.value;
    ui.intervalInput.value = config.intervalSeconds || ui.intervalInput.value;
    ui.watchdogIntervalInput.value = config.watchdogIntervalMinutes ?? ui.watchdogIntervalInput.value;
    ui.restartCountInput.value = config.restartCount ?? ui.restartCountInput.value;
    ui.restartIntervalInput.value = config.restartIntervalMinutes ?? ui.restartIntervalInput.value;
    ui.autoStartInput.checked = config.autoStart !== false;
  }

  const passwordSet = Boolean(config.passwordConfigured);
  ui.passwordConfigured.textContent = passwordSet ? "已保存加密密码" : "尚未保存密码";
  ui.passwordConfigured.parentElement.classList.toggle("set", passwordSet);
  ui.passwordInput.required = !passwordSet;
  ui.passwordInput.placeholder = passwordSet ? "留空则不修改" : "首次配置必填";

  if (Array.isArray(data.log?.lastLines) && state.logsLoading === false) {
    renderLogs(data.log.lastLines);
  }
}

function renderLogs(lines) {
  ui.logOutput.textContent = lines.length ? lines.join("\n") : "暂无日志";
  ui.logOutput.scrollTop = ui.logOutput.scrollHeight;
}

async function loadStatus({ silent = false } = {}) {
  if (state.statusLoading) return;
  state.statusLoading = true;
  ui.refreshButton.disabled = true;
  try {
    const result = await api("/api/status");
    updateStatus(result.data);
  } catch (error) {
    setConnection("danger", "连接失败");
    if (!silent) showToast(error.message, true);
  } finally {
    state.statusLoading = false;
    ui.refreshButton.disabled = false;
  }
}

async function loadLogs({ silent = false } = {}) {
  if (state.logsLoading) return;
  state.logsLoading = true;
  try {
    const result = await api(`/api/logs?tail=${encodeURIComponent(ui.logTail.value)}`);
    renderLogs(result.data.lines || []);
    ui.logMeta.textContent = `${result.data.path} · ${result.data.lines.length} 行`;
  } catch (error) {
    if (!silent) showToast(error.message, true);
  } finally {
    state.logsLoading = false;
  }
}

function setActionState(busy) {
  state.actionLoading = busy;
  document.querySelectorAll("[data-action]").forEach((button) => {
    button.disabled = busy || !state.taskConfigured;
  });
}

async function runAction(action) {
  if (state.actionLoading) return;
  const labels = {
    start: "启动任务",
    stop: "终止任务",
    restart: "重启任务",
    check: "立即检测",
    "force-login": "强制登录",
  };
  setActionState(true);
  showToast(`${labels[action] || "操作"}执行中...`);
  try {
    const result = await api("/api/action", {
      method: "POST",
      body: JSON.stringify({ action }),
    });
    showToast(result.message || "操作已完成");
    await Promise.all([loadStatus(), loadLogs()]);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setActionState(false);
  }
}

async function saveConfig(event) {
  event.preventDefault();
  const submitButton = ui.configForm.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  try {
    const payload = {
      account: ui.accountInput.value.trim(),
      operator: ui.operatorSelect.value,
      password: ui.passwordInput.value,
      portalUrl: ui.portalInput.value.trim(),
      intervalSeconds: Number(ui.intervalInput.value),
      watchdogIntervalMinutes: Number(ui.watchdogIntervalInput.value),
      restartCount: Number(ui.restartCountInput.value),
      restartIntervalMinutes: Number(ui.restartIntervalInput.value),
      autoStart: ui.autoStartInput.checked,
    };
    const result = await api("/api/config", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    ui.passwordInput.value = "";
    state.configDirty = false;
    showToast(result.message || "配置已更新");
    await Promise.all([loadStatus(), loadLogs()]);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    submitButton.disabled = false;
  }
}

async function detectPortal({ automatic = false } = {}) {
  const previousValue = ui.portalInput.value;
  ui.detectPortalButton.disabled = true;
  try {
    const result = await api("/api/detect-portal");
    if (ui.portalInput.value === previousValue) {
      ui.portalInput.value = result.data.portalUrl;
      state.configDirty = true;
      showToast("已自动获取校园门户地址，请保存并应用。");
    }
  } catch (error) {
    if (!automatic) showToast(error.message, true);
  } finally {
    ui.detectPortalButton.disabled = false;
  }
}

async function downloadLog() {
  ui.downloadLogButton.disabled = true;
  try {
    const response = await fetch("/api/download-log", {
      headers: { "X-HTU-Token": token },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || `下载失败：HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "campus-auto-login.log";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    ui.downloadLogButton.disabled = false;
  }
}

function bindEvents() {
  ui.refreshButton.addEventListener("click", () => loadStatus());
  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => runAction(button.dataset.action));
  });
  ui.configForm.addEventListener("submit", saveConfig);
  ui.configForm.addEventListener("input", () => {
    state.configDirty = true;
  });
  ui.configForm.addEventListener("change", () => {
    state.configDirty = true;
  });
  ui.intervalDown.addEventListener("click", () => {
    ui.intervalInput.value = Math.max(5, Number(ui.intervalInput.value || 10) - 5);
    state.configDirty = true;
  });
  ui.intervalUp.addEventListener("click", () => {
    ui.intervalInput.value = Math.min(3600, Number(ui.intervalInput.value || 10) + 5);
    state.configDirty = true;
  });
  ui.logTail.addEventListener("change", () => loadLogs());
  ui.autoRefresh.addEventListener("change", () => {
    if (ui.autoRefresh.checked) {
      loadStatus();
      loadLogs();
    }
  });
  ui.downloadLogButton.addEventListener("click", downloadLog);
  ui.detectPortalButton.addEventListener("click", () => detectPortal());
}

bindEvents();
loadStatus().then(() => {
  if (!ui.accountInput.value) {
    ui.accountInput.focus();
    if (!ui.portalInput.value) {
      detectPortal({ automatic: true });
    }
  }
});
loadLogs();

window.setInterval(() => {
  if (ui.autoRefresh.checked && document.visibilityState === "visible") {
    loadStatus({ silent: true });
    loadLogs({ silent: true });
  }
}, 5000);

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    loadStatus({ silent: true });
    loadLogs({ silent: true });
  }
});
