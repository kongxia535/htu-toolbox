# HTU Connect · 校园网助手

河师大校园网自动登录工具。桌面端使用本地 Python 服务与响应式网页，Android 使用 Kotlin 原生应用。保留独立的 Rust 命令行工具。

## 平台与运行方式

| 平台 | 界面 | 自动登录与后台运行 | 密码保存 |
| --- | --- | --- | --- |
| Windows 10/11 | 本机网页 | Windows 计划任务、PowerShell watcher | 当前用户 DPAPI |
| Linux | 本机网页 | Python watcher；可安装 systemd 用户服务 | Fernet 本机加密文件，权限 0600 |
| macOS | 本机网页 | Python watcher；可安装 LaunchAgent | Fernet 本机加密文件，权限 0600 |
| Android 8.0+ | Kotlin 原生界面 | 带通知的前台服务；可选择开机恢复 | Android Keystore AES-GCM |

认证仅适用于设备连接河师大校园网络的情况。门户地址目前限定为 `http(s)://10.101.2.194:6060/portal.do`，需保留完整查询参数。公网探针返回预期内容才判断在线；认证通过与联网验证通过分别展示。

### Windows

需要 Windows PowerShell 5.1、Python **3.10+**（加入 PATH）。网页和自动登录不需要 Rust。

1. 完整解压源码或发布包，运行根目录 `Setup.cmd`。
2. 本机浏览器打开控制台后，填写账号、运营商和密码，点击自动获取或粘贴完整门户地址。
3. 点击“保存并连接”。后续保存时密码留空会保留已有密文。

控制台与自动登录是两个独立计划任务。自动恢复选项控制登录后的启动及看门狗触发。停止操作禁用任务并结束当前安装目录下的进程；重新启动会启用任务。

```powershell
# 单次检测。失败返回非零退出码；不会修改常驻任务。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\CampusNetAutoLogin.ps1 -Once -ShowStatus
# 卸载任务，保留账号与日志
.\scripts\Uninstall-CampusNetAutoLogin.ps1
.\scripts\Uninstall-WebDashboard.ps1
```

Windows 配置为 `runtime/campus-auto-login.json`。密码绑定当前 Windows 用户，换用户或设备后需要重新输入。

### Linux / macOS

需要 Python **3.10+**，不依赖 PowerShell。

```bash
bash scripts/start.sh
```

脚本建立 `.venv`、安装 `requirements.txt` 并启动本机控制台。默认端口 8765；可传 `--port 8877`。直接开发启动：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m web.server --open-browser
```

网页服务存活时，内部 watcher 持续检测与退避重试。开启“自动恢复登录”后，服务再次启动时恢复 watcher。**系统登录后自启**需要另外安装用户服务：先停止前台实例，避免端口冲突，再运行：

```bash
.venv/bin/python scripts/install-user-service.py
# 停止并卸载用户服务，保留账号配置
.venv/bin/python scripts/install-user-service.py --remove
```

Linux 要求可用的 systemd 用户会话；macOS 使用当前用户 LaunchAgent。网页仅监听回环地址，不提供局域网远程控制。可用 `HTU_RUNTIME_DIR` 指定本机数据目录。

Linux/macOS 使用 `runtime/desktop-config.json` 和 `runtime/credential.key`。密钥与密文保存在同一设备，依靠用户文件权限保护，**不等同于硬件密钥库**；不要分享或提交整个 `runtime/`。加密文件不是 Windows DPAPI 配置，跨平台需要重新设置账号。

### Android 原生 APK

Android 源码在 `android/`，使用原生控件，不依赖 WebView、Python 或 Termux。

1. 安装调试 APK，打开 **HTU Connect**，填写账号和门户地址。
2. 保存并连接，允许通知。自动登录以可见前台服务运行，可在应用或通知中停止。
3. 可开启“开机后恢复自动登录”。停止服务后不会因开机选项重新启动，需手动再次开启。

联网请求优先使用 Wi-Fi 网络，避免未认证 Wi-Fi 时请求误走移动数据。部分厂商系统仍需手动允许后台运行；强制停止应用后需重新打开。应用禁止系统备份密码数据，Keystore 密钥不能随 APK 或配置迁移。HTTP 明文仅允许校园门户和指定探针域名。

构建需要 JDK 17+、Android SDK 36 / Build Tools 36.0.0：

```bash
cd android
./gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
```

APK 在 `android/app/build/outputs/apk/debug/app-debug.apk`。调试签名用于安装验证；正式发布需由项目维护者配置自己的签名密钥，项目不保存密钥。

版本信息统一配置在 `android/version.properties`，Gradle 和独立 SDK 构建使用同一版本号。

Maven 不可用时，也可使用已安装的 Android SDK 与官方 Kotlin 2.1.20 编译器直接构建：

```bash
python3 scripts/build-android.py --sdk /path/to/android-sdk --kotlin /path/to/kotlinc
```

此方式生成并校验调试 APK：`dist/htu-connect-debug.apk`，需要 SDK Platform 36、Build Tools 36.0.0 和 JDK 17+。编译器安装包应校验官方 SHA-256；脚本不自动下载或关闭任何校验。可额外传 `--junit` 和 `--hamcrest` 指定 JUnit 4.13.2 与 Hamcrest jar，执行现有 Android 单元测试。


## Rust 命令行工具

Rust CLI 与网页/Android 配置独立。使用固定 Rust 1.90.0 及 libcurl 开发依赖，云环境使用 Rust 1.90 验证。

```bash
cargo build --workspace
cargo run -p htu-toolbox-cli -- --help
cargo run -p htu-toolbox-cli -- net set
cargo run -p htu-toolbox-cli -- net login
cargo run -p htu-toolbox-cli -- net logout
```

命令完成后直接退出，失败返回非零退出码；交互终端需要停留时使用 `--pause`。支持 `yd`、`lt`、`dx`、`hsd`。配置在系统配置目录下的 `htu-toolbox/config.toml`，目前 Rust CLI 仍以 TOML 保存密码，请保护此文件。

## 开发与验证

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
cargo test --workspace
```

Windows 另运行 `tests/Test-Watcher.ps1`，通过模拟认证检查单次执行结果。Android 执行上述 Gradle 测试与 lint。CI 配置在 `.github/workflows/verify.yml`，覆盖三个桌面系统及 Android 构建。

```text
web/config.py       参数校验、原子配置保存、桌面密码加密
web/network.py      探针、门户发现、认证请求
web/runtime.py      后台 watcher、操作互斥、平台适配
web/windows.py      Windows 计划任务适配
web/server.py       本机 HTTP/API 服务
web/static/         响应式网页、深浅主题
android/            原生应用、Keystore、前台服务
htu-toolbox-lib/    Rust HTTP 与认证库
htu-toolbox-cli/    Rust 命令行入口
scripts/            平台安装、启动、停止与打包
```

配置、日志、PID 位于 Git 忽略的 `runtime/`；日志轮转，网页最多导出最近 1000 行。Windows 发布包可用 `scripts/Package-Release.ps1` 生成，不包括运行数据。
