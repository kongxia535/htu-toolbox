# htu-toolbox

河师大校园网登录工具。本 fork 在上游 Rust 命令行工具的基础上，增加了 Windows 断网自动登录、后台计划任务和本地网页控制台。

## Windows 自动登录

适用环境：Windows 10/11、Windows PowerShell 5.1、Python 3（安装时需加入 PATH）。网页自动登录功能不需要 Rust。

1. 从[本仓库 Releases](https://github.com/kongxia535/htu-toolbox/releases)下载 `htu-toolbox-community.zip` 并完整解压，或下载本仓库源码。
2. 双击根目录的 `Setup.cmd`。它会安装并启动本地网页控制台，在浏览器打开 `http://127.0.0.1:8765/`。
3. 首次使用时，在网页填写上网账号、密码、运营商及校园门户地址。可点击“自动获取”；若当前网络已认证或没有返回门户重定向，请手动粘贴完整的门户地址。
4. 点击“保存并应用”安装并启动自动登录任务。以后再次运行 `Setup.cmd` 只会重新安装/打开控制台，不会重置已有账号配置。

控制台仅监听本机回环地址。页面可查看网络与计划任务状态、常驻进程、看门狗时间及运行日志，也可启动、终止、重启任务，立即检测或强制登录。账号配置里可以调整轮询间隔（默认 10 秒）、开机自启、看门狗间隔、自动重启次数和重启等待时间。停止任务会禁用其计划任务与看门狗，并结束对应的常驻进程；再次启动会恢复任务。

探针以直接请求公网 IP 的方式检测连通性，不依赖普通 DNS 解析或系统代理；网络不可用或被校园门户拦截时尝试登录。登录失败会退避重试。门户地址自动获取仅识别项目支持的校园门户，不能保证在已认证或未连接校园网时成功。

密码由当前 Windows 用户的 DPAPI 加密后写入 `runtime/campus-auto-login.json`；日志位于 `runtime/campus-auto-login.log`。`runtime/` 已被 Git 忽略，不应手动上传或分享。换电脑或换 Windows 用户时需重新配置密码。

### 任务维护

在项目根目录打开 PowerShell，可手动执行一次检测：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\CampusNetAutoLogin.ps1 -Once -ShowStatus
```

查看计划任务：

```powershell
Get-ScheduledTask -TaskName HTU-CampusNet-AutoLogin
Get-ScheduledTaskInfo -TaskName HTU-CampusNet-AutoLogin
Get-ScheduledTask -TaskName HTU-CampusNet-Dashboard
```

卸载两个后台任务并保留加密配置及日志：

```powershell
.\scripts\Uninstall-CampusNetAutoLogin.ps1
.\scripts\Uninstall-WebDashboard.ps1
```

如需同时删除自动登录配置和日志，可给第一条卸载命令加上 `-RemoveData`。仅重新安装网页控制台可运行 `.\scripts\Install-WebDashboard.ps1 -Port 8765`。网页控制台和自动登录探针是两个独立的计划任务。

## Rust 命令行工具

仓库保留上游的 Rust CLI，可单次登录/登出校园网；它与 Windows 网页自动登录任务互不依赖。已安装 Rust 工具链时，可从源码安装：

```bash
cargo install htu-toolbox-cli --git https://github.com/kongxia535/htu-toolbox
```

运行 `htu-toolbox-cli`；首次启动会提示配置账号，之后启动时默认尝试登录。命令行工具的配置与 Windows 网页控制台的 `runtime/` 配置不是同一份。

欢迎通过 Issue 反馈问题或提交 PR。
