# htu-toolbox

河师大工具箱

## :construction: WIP :construction:

本项目还在测试中，如有bug请及时提交issue。

欢迎提交PR来完善本项目。

## 功能

-   [x] 校园网登录

## 一键安装（Windows）

环境要求：Windows 10/11、Windows PowerShell 5.1、Python 3。

1. 下载并完整解压项目。
2. 双击根目录的 `Setup.cmd`。
3. 第一次运行时输入上网账号、密码、运营商和校园门户地址。
4. 安装完成后会自动打开本地控制台：`http://127.0.0.1:8765/`。

密码使用当前 Windows 用户的 DPAPI 加密保存在 `runtime/campus-auto-login.json`。`runtime/` 

## 指令行版本

### 安装

-   从release下载

在[release页](https://github.com/arkuna23/htu-toolbox/releases)根据你的操作系统下载可用的可执行文件

-   或是使用`cargo install`

需要确保你安装了rust工具链。

```bash
cargo install htu-toolbox-cli --git https://github.com/arkuna23/htu-toolbox
```

### 快速开始

#### 校园网登录

1. 首先需要设定你的校园网账号

```bash
htu-toolbox-cli
```

或 双击下载的可执行文件启动(Windows)

第一次启动会有校园网账号设置向导，按照向导输入信息，回车确认，上下键选择

2. 登录校园网

启动程序，自动登录(启动程序默认行为是登录校园网)

## Windows 断网自动登录

`scripts/CampusNetAutoLogin.ps1` 是不依赖 Rust 工具链的常驻探针，默认每 10 秒检测一次网络。探针直接请求公网 IP，并显式禁用系统代理和普通 DNS 解析；检测到断网或被校园门户拦截后，直接向校园门户 IP 提交认证。

安装当前用户的开机自动任务：

```powershell
$password = Read-Host -Prompt '校园网密码' -AsSecureString
.\scripts\Install-CampusNetAutoLogin.ps1 `
  -Account YOUR_STUDENT_ID `
  -Password $password `
  -Operator lt `
  -PortalUrl '从浏览器复制的完整校园门户地址'
```

密码使用 Windows DPAPI 加密后写入 `runtime/campus-auto-login.json`，只允许当前 Windows 用户解密。运行日志位于 `runtime/campus-auto-login.log`，脚本按状态变化记录，不会每 10 秒刷屏。

计划任务同时包含登录触发器和每 5 分钟的看门狗触发器；脚本常驻进程若意外退出，任务会自动重新拉起。登录连续失败时探针不会退出，而是按 10、20、40、60 秒逐步退避后继续重试。

手动做一次检测：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\CampusNetAutoLogin.ps1 -Once -ShowStatus
```

查看后台任务：

```powershell
Get-ScheduledTask -TaskName HTU-CampusNet-AutoLogin
Get-ScheduledTaskInfo -TaskName HTU-CampusNet-AutoLogin
```

卸载任务并保留加密配置：

```powershell
.\scripts\Uninstall-CampusNetAutoLogin.ps1
```

## 本地网页控制台

网页控制台只监听本机回环地址，不向局域网或公网开放：

```text
http://127.0.0.1:8765/
```

页面可以查看任务状态、网络状态、进程 PID、下次看门狗时间、运行日志，并可以启动、停止、重启、立即检测、强制登录和修改账号配置。

网页服务安装为当前用户的计划任务，登录后自动运行，异常退出后由看门狗重新拉起。手动安装或重新应用：

```powershell
.\scripts\Install-WebDashboard.ps1 -Port 8765
```

卸载网页服务：

```powershell
.\scripts\Uninstall-WebDashboard.ps1 -Port 8765
```

## 发布打包

生成不包含 `runtime/`、日志、缓存和本机配置的社区发布包：

```powershell
.\scripts\Package-Release.ps1
```

脚本会在 `dist/` 下生成 ZIP 和 SHA256 文件，并在压缩前检查账号、密码、MAC、内网 IP 和本机用户名等敏感信息。
