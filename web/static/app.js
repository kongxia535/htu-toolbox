"use strict";
const token = document.querySelector('meta[name="htu-token"]').content;
const $ = (id) => document.getElementById(id);
let configured = false,
  busy = false,
  dirty = false,
  initialized = false,
  loadingStatus = false;
let logsController;
const dirtyFields = new Set();
const defaults = {
  account: "",
  operator: "lt",
  portalUrl: "",
  intervalSeconds: 10,
  watchdogIntervalMinutes: 5,
  restartCount: 999,
  restartIntervalMinutes: 1,
  autoStart: true,
};
const fields = {
  account: "accountInput",
  operator: "operatorSelect",
  portalUrl: "portalInput",
  intervalSeconds: "intervalInput",
  watchdogIntervalMinutes: "watchdogIntervalInput",
  restartCount: "restartCountInput",
  restartIntervalMinutes: "restartIntervalInput",
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
  return new Date(
    typeof value === "number" ? value * 1000 : value,
  ).toLocaleTimeString("zh-CN", { hour12: false });
}
function setBusy(value) {
  busy = value;
  $("configForm").setAttribute("aria-busy", String(value));
  $("configForm")
    .querySelectorAll("input,select,textarea,button")
    .forEach((el) => (el.disabled = value));
  document
    .querySelectorAll("[data-action]")
    .forEach((el) => (el.disabled = value || !configured));
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
      : "未联网";
  $("networkHint").textContent = network.online
    ? "已确认互联网连接"
    : network.errors?.[0] || "请检查校园网络";
  $("processState").textContent = task.stopping
    ? "停止中"
    : Number(task.watcherCount) > 0
      ? "运行中"
      : "未运行";
  $("processHint").textContent = task.processIds?.length
    ? `PID ${task.processIds.join(", ")}`
    : "未检测到后台任务";
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
  $("windowsOptions").hidden = platform.backend !== "scheduled-task";
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
  logsController?.abort();
  logsController = new AbortController();
  const current = logsController;
  const timer = setTimeout(() => current.abort(), 12000);
  try {
    const { data } = await api(`/api/logs?tail=${$("logTail").value}`, {
      signal: current.signal,
    });
    if (logsController !== current) return;
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
    if (logsController === current) $("logMeta").textContent = error.message;
  } finally {
    clearTimeout(timer);
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
      timeout: 80000,
    });
    $("passwordInput").value = "";
    dirty = false;
    dirtyFields.clear();
    toast(result.message);
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
        timeout: 90000,
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
    const response = await fetch("/api/download-log", {
      headers: { "X-HTU-Token": token },
      signal: AbortSignal.timeout(12000),
    });
    if (!response.ok) throw new Error("日志导出失败。");
    const url = URL.createObjectURL(await response.blob()),
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
function theme(value) {
  document.documentElement.dataset.theme = value;
  $("themeButton").setAttribute(
    "aria-label",
    value === "dark" ? "切换浅色主题" : "切换深色主题",
  );
}
try {
  theme(
    localStorage.getItem("htu-theme") ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"),
  );
} catch {
  theme("light");
}
$("themeButton").addEventListener("click", () => {
  const value =
    document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  theme(value);
  try {
    localStorage.setItem("htu-theme", value);
  } catch {}
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
