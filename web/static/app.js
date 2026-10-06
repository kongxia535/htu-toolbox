"use strict";
const token = document.querySelector('meta[name="htu-token"]').content;
const $ = (id) => document.getElementById(id);
let configured = false,
  busy = false,
  dirty = false,
  initialized = false,
  loadingStatus = false;
let loadingLogs = false;
let logLines = [];
const dirtyFields = new Set();
const defaults = {
  account: "",
  operator: "lt",
  portalUrl: "",
  intervalSeconds: 10,
  autoStart: false,
};
const fields = {
  account: "accountInput",
  operator: "operatorSelect",
  portalUrl: "portalInput",
  intervalSeconds: "intervalInput",
  autoStart: "autoStartInput",
};
function toast(message, error = false) {
  $("toast").textContent = message;
  $("toast").classList.toggle("error", error);
  $("toast").classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $("toast").classList.remove("show"), 5500);
}
async function api(path, { timeout = 20000, ...options } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const signal = options.signal || controller.signal;
  const headers = new Headers(options.headers || {});
  headers.set("X-HTU-Token", token);
  if (options.body) headers.set("Content-Type", "application/json");
  try {
    const response = await fetch(path, {
      ...options,
      headers,
      signal,
      cache: "no-store",
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok)
      throw new Error(payload.error || `请求失败 (${response.status})`);
    return payload;
  } catch (error) {
    if (error.name === "AbortError")
      throw new Error("请求超时，请稍后刷新状态确认结果。");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
function date(value) {
  if (!value) return "—";
  return new Date(Number(value) * 1000).toLocaleTimeString("zh-CN", {
    hour12: false,
  });
}
function setBusy(value) {
  busy = value;
  $("configForm").setAttribute("aria-busy", String(value));
  $("configForm")
    .querySelectorAll("input,select,textarea,button")
    .forEach((el) => (el.disabled = value));
  document
    .querySelectorAll("[data-action]")
    .forEach(
      (el) =>
        (el.disabled = value || (!configured && el.dataset.action !== "check")),
    );
  $("saveButton").textContent = value ? "正在处理…" : "保存并连接";
}
function render(data) {
  const { task = {}, network = {}, config = {}, platform = {} } = data;
  configured = !!config.passwordConfigured && task.ok !== false;
  const running = task.state === "Running";
  const labels = {
    Running: "运行中",
    Ready: "已暂停",
    Disabled: "已暂停",
    NotInstalled: "未配置",
    Unknown: "读取失败",
  };
  $("taskState").textContent = labels[task.state] || "等待启动";
  $("taskHint").textContent =
    task.error || (configured ? "账号已配置" : "请先保存账号");
  $("networkState").textContent = network.online
    ? "在线"
    : network.state === "captive"
      ? "待认证"
      : network.state === "error"
        ? "检测失败"
        : "尚未检测";
  $("networkHint").textContent = network.online
    ? "已确认互联网连接"
    : network.message || "点击立即检测查看网络状态";
  $("nextRun").textContent = date(task.nextRunTime);
  $("lastRun").textContent = task.lastRunTime
    ? `上次 ${date(task.lastRunTime)}`
    : "暂无检测记录";
  $("connectionText").textContent =
    task.ok === false
      ? "后台状态读取失败"
      : running
        ? "自动登录已开启"
        : configured
          ? "自动登录已暂停"
          : "等待账号配置";
  $("connectionPill").className =
    `status-pill ${task.ok === false ? "danger" : running ? "success" : "neutral"}`;
  $("lastUpdate").textContent =
    `更新于 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
  if (task.lastResult?.message)
    $("lastResult").textContent = task.lastResult.message;
  $("platformBadge").textContent = platform.name || "本地服务";
  $("platformHint").textContent =
    platform.autostartHint || "服务仅在本机运行。";
  $("storageHint").textContent = "账号配置保存在本机，密码加密存储。";
  $("passwordConfigured").textContent = config.passwordConfigured
    ? "已保存 · 留空保留"
    : "首次配置必填";
  $("passwordInput").required = !config.passwordConfigured;
  if ((!initialized || !dirty) && !busy) {
    for (const [key, id] of Object.entries(fields)) {
      if (dirtyFields.has(id)) continue;
      const value = config[key] ?? defaults[key];
      if (key === "autoStart") $(id).checked = value;
      else $(id).value = value;
    }
    initialized = true;
  }
  setBusy(busy);
}
async function loadStatus() {
  if (loadingStatus) return;
  loadingStatus = true;
  $("refreshButton").disabled = true;
  try {
    render((await api("/api/status", { timeout: 30000 })).data);
  } catch (error) {
    $("connectionText").textContent = "服务连接失败";
    $("connectionPill").className = "status-pill danger";
  } finally {
    loadingStatus = false;
    $("refreshButton").disabled = false;
  }
}
async function loadLogs() {
  if (loadingLogs) return;
  loadingLogs = true;
  try {
    const { data } = await api(`/api/logs?tail=${$("logTail").value}`, {
      timeout: 12000,
    });
    logLines = data.lines;
    const text = data.lines.length ? data.lines.join("\n") : "暂无记录";
    const bottom =
      $("logOutput").scrollHeight -
        $("logOutput").scrollTop -
        $("logOutput").clientHeight <
      40;
    $("logOutput").textContent = text;
    if (bottom) $("logOutput").scrollTop = $("logOutput").scrollHeight;
    $("logMeta").textContent =
      `${data.lines.length} 行${data.lastWriteTime ? ` · ${date(data.lastWriteTime)}` : ""}`;
  } catch (error) {
    $("logMeta").textContent = error.message;
  } finally {
    loadingLogs = false;
  }
}
function markDirty(event) {
  dirty = true;
  dirtyFields.add(event.target.id);
}
$("configForm").addEventListener("input", markDirty);
$("configForm").addEventListener("change", markDirty);
$("configForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  const payload = { password: $("passwordInput").value };
  for (const [key, id] of Object.entries(fields))
    payload[key] =
      key === "autoStart"
        ? $(id).checked
        : typeof defaults[key] === "number"
          ? Number($(id).value)
          : $(id).value.trim();
  setBusy(true);
  try {
    const result = await api("/api/config", {
      method: "POST",
      body: JSON.stringify(payload),
      timeout: 20000,
    });
    $("passwordInput").value = "";
    dirty = false;
    dirtyFields.clear();
    const started = await api("/api/action", {
      method: "POST",
      body: JSON.stringify({ action: "start" }),
      timeout: 30000,
    });
    toast(`${result.message} ${started.message}`);
    await Promise.all([loadStatus(), loadLogs()]);
  } catch (error) {
    toast(error.message, true);
  } finally {
    setBusy(false);
  }
});
document.querySelectorAll("[data-action]").forEach((button) =>
  button.addEventListener("click", async () => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await api("/api/action", {
        method: "POST",
        body: JSON.stringify({ action: button.dataset.action }),
        timeout: 30000,
      });
      $("lastResult").textContent = result.message;
      toast(result.message);
    } catch (error) {
      $("lastResult").textContent = error.message;
      toast(error.message, true);
    } finally {
      setBusy(false);
      await Promise.all([loadStatus(), loadLogs()]);
    }
  }),
);
$("detectPortalButton").addEventListener("click", async () => {
  const oldValue = $("portalInput").value;
  $("detectPortalButton").disabled = true;
  try {
    const { data } = await api("/api/detect-portal");
    if ($("portalInput").value === oldValue) {
      $("portalInput").value = data.portalUrl;
      dirty = true;
      dirtyFields.add("portalInput");
      toast("已获取门户地址，请保存配置。");
    }
  } catch (error) {
    toast(error.message, true);
  } finally {
    $("detectPortalButton").disabled = busy;
  }
});
$("refreshButton").addEventListener("click", () =>
  Promise.all([loadStatus(), loadLogs()]),
);
$("logTail").addEventListener("change", loadLogs);
$("toggleLogButton").addEventListener("click", () => {
  const collapsed = $("logPanel").classList.toggle("collapsed");
  $("toggleLogButton").textContent = collapsed ? "展开" : "收起";
  $("toggleLogButton").setAttribute("aria-expanded", String(!collapsed));
});
$("downloadLogButton").addEventListener("click", async () => {
  $("downloadLogButton").disabled = true;
  try {
    const url = URL.createObjectURL(
        new Blob([logLines.join("\n")], { type: "text/plain;charset=utf-8" }),
      ),
      link = document.createElement("a");
    link.href = url;
    link.download = "htu-connect.log";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    toast(error.message, true);
  } finally {
    $("downloadLogButton").disabled = false;
  }
});
setBusy(false);
async function poll() {
  if (document.visibilityState === "visible" && $("autoRefresh").checked)
    await Promise.all([loadStatus(), loadLogs()]);
  setTimeout(poll, 5000);
}
Promise.all([loadStatus(), loadLogs()]).finally(() => setTimeout(poll, 5000));
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") loadStatus();
});
