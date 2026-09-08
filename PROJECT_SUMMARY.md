# iLifeTrack 项目总结

## 项目定位

iLifeTrack 是一个个人使用的 Apple“查找”设备历史轨迹与本机通讯归档工具。

它目前不是 iPhone/iPad App，而是一个运行在 Mac 上的原生 GUI 应用：

- Mac 定时从 Apple 获取设备的最后已知位置。
- 秒级监视已同步到 Mac 的新短信、iMessage 和通话记录。
- 新位置被加密保存到本地。
- 用户通过原生 Apple 地图查看轨迹。
- 日常操作全部在 GUI 中完成，不需要命令行。

当前使用的是 `iCloudPy`，没有使用 `FindMy.py`。主要原因是现阶段需要查询 Apple 账户下的 iPhone、iPad、Mac 等设备，而 `FindMy.py` 更偏向 Find My Network/AirTag 报告；同时其设备密钥提取在当前 macOS 版本上存在兼容性问题。

## 整体架构

```text
Apple 私有 iCloud/Find My 接口
              │
              ▼
      iCloudPy 数据提供层
              │
              ▼
      Python 后台采集程序
       │              ├── 本机“信息”与通话数据库（只读）
       │              │
       │              └── 采集日志与运行统计
       ▼
AES-256-GCM 加密的 SQLite 数据库
       │
       ▼
SwiftUI 原生 macOS 应用
       │
       └── MapKit 地图、轨迹、时间轴和设置界面

macOS launchd
└── 负责登录后自动启动和持续后台采集
```

认证由 GUI 启动一个本地认证桥接进程完成。Apple 账户密码和验证码通过本机进程管道传递，不放入命令参数，也不写入配置文件。GUI 显式重新认证时，先将旧会话复制到隔离目录，在副本中保留 trusted-browser cookie 和 trust token，再强制用新密码刷新；只有登录、2FA 和 Find My 设备读取都成功后，才原子替换原会话。中国大陆账户通过全球 `idmsa.apple.com` 完成密码认证，再通过 `icloud.com.cn` 和 `setup.icloud.com.cn` 访问区域服务。刷新前会丢弃旧的 `scnt`/session ID，并在 SRP `signin/init` 后把 Apple 新签发的握手头传给 `signin/complete`。

## 技术栈

### macOS GUI

- Swift 6
- SwiftUI
- Apple MapKit
- CryptoKit
- Security Framework
- SQLite3
- 最低系统版本：macOS 14

主要代码：

- `viewer/Sources/iLifeTrack/ContentView.swift`
- `viewer/Sources/iLifeTrack/RecordingSettingsView.swift`
- `viewer/Sources/iLifeTrack/TrackStore.swift`

### 后台采集

- Python 3.12，代码兼容 Python 3.10–3.14
- `icloudpy 0.9.0`
- `cryptography`
- `keyring`
- PyInstaller（将 Python 运行时和依赖封装进 `.app`）
- SQLite
- macOS LaunchAgent
- `uv` 管理虚拟环境和依赖

主要代码：

- `src/ilifetrack/provider.py`
- `src/ilifetrack/collector.py`
- `src/ilifetrack/database.py`
- `src/ilifetrack/crypto.py`

### 开发质量

- pytest：目前 31 项 Python 测试全部通过
- Swift Testing：目前 7 项坐标校正和通知测试全部通过
- Ruff：格式和静态检查通过
- Swift Release 构建通过
- GUI 已进行实际界面操作验证

## 文件夹结构

下面只列出需要维护的源文件。`.venv/`、`build/`、`viewer/.build/`、缓存目录和 `*.egg-info` 都是自动生成内容，不应手动修改，也不需要提交到版本库。

```text
iLifeTrack/
├── README.md                       # 中文项目说明（默认）
├── README_EN.md                    # English documentation
├── PROJECT_SUMMARY.md              # 项目架构、维护和升级说明
├── pyproject.toml                  # Python 包、依赖、命令入口和工具配置
├── uv.lock                         # Python 依赖锁定文件
├── packaging/
│   └── ilifetrack_backend.py       # PyInstaller 后台程序入口
├── src/ilifetrack/                 # Python 后台与数据层
│   ├── cli.py                      # 后台命令入口，供 GUI 和 LaunchAgent 调用
│   ├── collector.py                # 位置采集、通讯轮询、重试和调度
│   ├── communications.py           # 读取本机信息与通话数据库
│   ├── config.py                   # 配置读写和校验
│   ├── crypto.py                   # 钥匙串、密钥派生和字段加密
│   ├── database.py                 # SQLite 表结构、去重、清除和保留策略
│   ├── gui_bridge.py               # GUI 登录和双重认证桥接
│   ├── models.py                   # Python 数据模型
│   ├── paths.py                    # 应用数据路径定义
│   ├── provider.py                 # iCloudPy/Find My 数据提供层
│   └── service.py                  # LaunchAgent 安装、启动和停止
├── tests/                          # Python 自动化测试
│   ├── test_collector.py
│   ├── test_communications.py
│   ├── test_config.py
│   ├── test_crypto.py
│   ├── test_database.py
│   ├── test_gui_bridge.py
│   └── test_provider.py
└── viewer/                         # 原生 macOS GUI
    ├── Package.swift               # Swift Package 配置
    ├── build-app.sh                # 完整构建、签名、安装脚本
    ├── build-icon.sh               # 从矢量源生成标准 macOS .icns
    ├── Resources/Info.plist        # App 名称、版本和权限说明
    ├── Resources/AppIcon.png       # 1024×1024 应用图标主图
    ├── Resources/AppIcon.icns      # 打包使用的 macOS 应用图标
    ├── Sources/iLifeTrack/
    │   ├── main.swift              # GUI/后台服务双模式启动入口
    │   ├── BackgroundServiceRunner.swift
    │   ├── ILifeTrackApp.swift
    │   ├── ContentView.swift       # 主窗口、地图和标签页
    │   ├── AuthenticationController.swift
    │   ├── RecordingController.swift
    │   ├── RecordingSettingsView.swift
    │   ├── CommunicationArchiveView.swift
    │   ├── TrackStore.swift        # 只读数据库、解密和轨迹查询
    │   ├── CoordinateCorrection.swift
    │   ├── ILifeTrackNotifications.swift
    │   └── CLIClient.swift         # 调用应用内置 Python 后台
    └── Tests/iLifeTrackTests/
        └── CoordinateCorrectionTests.swift
```

Python 部分负责认证、采集、加密、持久化和后台运行；Swift 部分负责用户交互、状态展示、数据库只读查询和地图绘制。两部分通过应用内置的命令行后台进程交互，但用户不需要直接使用命令行。

## 开发、测试和软件打包

### 开发环境

构建机器需要：

- Apple Silicon Mac。
- macOS 14 或更高版本。
- Xcode Command Line Tools 或完整 Xcode。
- `uv`。

首次拉取代码后，在项目根目录执行：

```bash
uv sync --extra dev
```

该命令会根据 `pyproject.toml` 和 `uv.lock` 创建 `.venv/`，并安装运行、测试和 PyInstaller 打包所需依赖。

### 修改后的验证流程

提交或打包前依次运行：

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
swift test --package-path viewer
swift build --package-path viewer -c release
```

涉及 GUI、后台服务、系统权限或真实 iCloud 返回数据的功能仍需进行实际操作验证；自动化测试不能替代这些系统集成检查。

### 打包成独立 Mac App

在项目根目录执行：

```bash
./viewer/build-app.sh
```

脚本会自动完成：

1. 使用 Swift Release 模式编译原生 GUI。
2. 使用 PyInstaller `--onedir` 打包 Python 后台、Python 运行时及依赖。
3. 从矢量源生成标准 `.icns`，组装 `iLifeTrack.app`，并将后台放进应用的 `Contents/Resources/backend/`。
4. 对后台可执行文件和整个 App 进行本机临时签名，并验证签名。
5. 先输出到项目的 `build/iLifeTrack.app`，再安全替换安装到 `/Applications/iLifeTrack.app`。
6. 如果后台服务原本已经安装，则用新版本 App 重新生成并启动 LaunchAgent。

最终包内主要结构是：

```text
iLifeTrack.app/
└── Contents/
    ├── Info.plist
    ├── MacOS/
    │   └── iLifeTrack                # 原生 GUI 与后台包装入口
    └── Resources/
        ├── AppIcon.icns
        └── backend/ilifetrack/
            ├── ilifetrack          # Python 后台入口
            └── _internal/           # Python 运行时和依赖库
```

因此目标 Mac 不需要单独安装 Python、`uv` 或项目源代码。安装后的 App 与开发目录相互独立；删除项目目录不会影响已安装应用，但不能删除 `~/Library/Application Support/iLifeTrack`，否则本地记录和配置会丢失。

### 打包后的检查

```bash
plutil -extract CFBundleShortVersionString raw "/Applications/iLifeTrack.app/Contents/Info.plist"
codesign --verify --deep --strict "/Applications/iLifeTrack.app"
file "/Applications/iLifeTrack.app/Contents/MacOS/iLifeTrack"
```

当前产物是 Apple Silicon `arm64` App。`build/` 还会包含 PyInstaller 的中间文件，可随时删除并重新生成；用户数据库、密钥、认证会话和配置不在 `build/` 中。

### 后台服务与重新打包

后台服务配置位于：

```text
~/Library/LaunchAgents/com.ilifetrack.app.plist
```

LaunchAgent 启动 `iLifeTrack.app/Contents/MacOS/iLifeTrack --background-service`，再由主程序运行包内 Python 后台。这样完全磁盘访问权限可以授予 `iLifeTrack.app` 本身，同时避免每次 Python 后台重新打包后路径或签名发生变化。

`build-app.sh` 会在检测到已安装后台服务时自动更新并重启它。重新签名后，macOS 仍有可能要求移除并重新添加“系统设置 → 隐私与安全性 → 完全磁盘访问权限”中的 iLifeTrack；通讯归档读取失败时应首先检查此项。

GUI 不依赖 macOS 没有对普通应用公开的 TCC 查询 API，而是对“信息”和通话历史数据库各执行一次只读查询。两者均可读时显示“完全磁盘访问：已授权”并隐藏设置按钮；从系统设置返回应用时会自动刷新。

### 版本号和依赖更新

当前版本是 **0.5.3（Build 25）**。本次补丁版本增加退出时的后台服务选择，并包含 iLifeTrack 品牌迁移、图标重制和文档整理；没有把尚未完成的第二阶段功能计入版本承诺。

发布新版本时至少检查：

- `viewer/Resources/Info.plist` 中的 `CFBundleShortVersionString` 和 `CFBundleVersion`。
- `pyproject.toml` 中的 Python 包版本与依赖。
- 修改依赖后重新运行 `uv lock`，并提交更新后的 `uv.lock`。
- 更新 `README.md`、本总结和相关自动化测试。

应用及其内部组件已统一使用 iLifeTrack 命名，包括 Python 包、Application Support 目录、LaunchAgent、钥匙串服务和后台二进制。旧版使用过的加密格式参数保持字节级兼容，以保证已有历史数据无需解密迁移即可继续读取。

### 分发给其他 Mac

当前脚本采用临时签名，适合这台 Mac 本地安装。若要分发给其他用户，还需要：

1. 使用 Apple Developer ID Application 证书正式签名，并启用 Hardened Runtime。
2. 将 App 或 DMG 提交 Apple 公证，等待通过后执行 stapling。
3. 在干净账户或另一台 Mac 上验证首次启动、钥匙串、LaunchAgent、2FA 和完全磁盘访问权限流程。
4. 如需兼容 Intel Mac，分别构建 `arm64` 与 `x86_64` 的 Swift 和 Python 产物，再制作 Universal 2 App；当前版本尚未实现。

分发包中不得包含开发者本人的 `config.json`、iCloud 会话、本地数据库、日志或钥匙串密钥。当前构建脚本只打包程序和依赖，不会把这些个人数据放入 `.app`。

## 当前主要功能

### 后台记录

- 开始和停止后台记录。
- 登录 Mac 后自动启动。
- 不设置总时长，可以持续运行直到手动停止。
- 退出应用时可选择仅退出界面并保留采集，或停止后台服务后退出。
- 支持 1、5、10、30 分钟快捷选项，以及 1–1440 分钟自定义间隔。
- 网络或 Apple 接口异常时指数退避，最长延迟到一小时。
- 认证失效时停止继续请求，等待用户重新认证。
- 修改间隔或设备选择后自动应用新设置。
- 后台采集器和 Python 运行时已经打包在应用内部。

### 设备管理

- 显示 Apple 账户当前可见设备。
- 支持勾选一台或多台设备。
- 支持刷新设备列表。
- iPhone、iPad、Mac 通常可以查询。
- AirPods 可能显示但不一定返回位置。
- 当前不支持 AirTag 加密报告。

### 地图轨迹

- 使用 Apple MapKit 原生地图。
- 蓝线连接历史位置。
- 支持点击单个位置点。
- 支持时间轴回放轨迹形成过程。
- 支持 1 小时、6 小时、24 小时、48 小时、7 天、自定义起止时间及全部历史。
- 支持查看定位精度、电量和旧位置状态。
- 支持中国大陆 WGS-84 → GCJ-02 地图显示校正，并可切换回原始坐标；数据库中的历史坐标不会被改写。

### 通讯归档

- 用户明确启用后，先导入 Mac 当前已有的消息和通话，再持续归档新增记录；重复导入自动去重。
- 约每 2 秒检查一次 Mac 本地“信息”和通话历史数据库。
- 支持短信、iMessage、来电和去电的本地查看、筛选与搜索。
- 系统记录经 iCloud 同步删除时，不联动删除本地归档。
- 需要为 `iLifeTrack.app` 授予 macOS 完全磁盘访问权限。
- 附件文件当前不复制；Mac 离线、休眠或记录未同步到 Mac 时无法保证捕获。

### 两种时间

- **位置时间**：设备产生位置，或者 Apple 报告该位置的时间。
- **采集时间**：Mac 从 Apple 取回并保存该位置的时间。

地图筛选和轨迹排序使用位置时间。设备离线、Apple 返回旧位置或接口延迟时，两个时间可能相差较大。

### 历史清除

- GUI 中可以清除全部轨迹。
- 操作前有明确确认，并自动创建可恢复的加密备份。
- 删除轨迹点、采集统计和移动测试记录。
- 保留 Apple 认证、设备列表、设备选择、采集间隔和后台运行状态。
- 如果后台仍在运行，清除后产生的新位置会继续保存。
- 可以按设备和位置时间范围清除轨迹。
- 可以设置永久保留、最近 30 天、90 天或 1 年的自动保留策略。

### 运行状态

- 显示后台服务是否正在运行。
- 显示最近一次成功采集和最近一次尝试。
- 显示最近一次采集结果。
- 显示下一次预计采集时间、最近错误和最新位置延迟。
- 显示每台设备最后一次位置时间和该位置的采集延迟。
- 显示轨迹点总量和历史数据起止时间。
- 显示数据库文件的本地存储占用。
- Apple 认证失效、采集异常和通讯权限异常首次出现时发送 macOS 通知。

### 自动加密备份

- 从 GUI 清除轨迹或通讯归档前，自动创建完整数据库快照。
- 备份保留数据库现有的字段级 AES-256-GCM 加密，不生成裸数据副本。
- 最多保留最近 20 个自动备份。
- GUI 显示最近备份时间、数量和大小，并可恢复最近备份。
- 恢复时暂停后台服务，恢复完成后自动重新启动；恢复前还会创建一个安全快照。

## 数据保存和安全

本地数据位于：

```text
~/Library/Application Support/iLifeTrack
```

安全设计包括：

- 轨迹、设备名称、消息、号码、联系人名称和通话详情使用 AES-256-GCM 加密。
- 32 字节主密钥保存在 macOS 钥匙串。
- 使用 HKDF-SHA256 派生加密密钥和索引密钥。
- 数据库中的设备短标识通过 HMAC 生成，不能直接还原 Apple 原始设备 ID。
- 重复位置通过加密指纹去重。
- Swift 地图查看器以只读模式打开数据库。
- 坐标只在查看器内存中解密。
- 会话、数据库、配置和日志文件权限限制为当前用户。
- 日志不记录坐标、密码或验证码。

`config.json` 中包含 Apple 账户名、采集间隔和设备短标识，但不包含密码、验证码或坐标。iCloud 会话目前保存在权限受限的会话文件中。

## 当前运行状态

- 后台服务正在运行。
- 当前间隔为 5 分钟。
- 最近一次检查时，最近 48 小时采集成功率为 100%。
- GUI 安装在 `/Applications/iLifeTrack.app`。
- 图形界面使用教程位于 `README.md`。

运行状态属于动态信息，应以应用当时显示的结果为准。

## 当前限制和风险

最大风险是 Apple 没有提供面向第三方的公开 Find My 位置读取 API。

因此：

- Apple 随时可能修改接口或登录流程。
- 不能保证长期稳定。
- 请求过于频繁可能触发限流或重新认证。
- 不适合作为救援、儿童安全或防盗系统。
- 很难以当前方式通过 App Store 审核。
- Mac 休眠、关机或断网期间不能采集。
- Apple 返回的是最后已知位置，不是真正的连续 GPS 数据流。
- 目前没有正式的数据库版本迁移框架。

## 建议升级路线

### 第一阶段：完善 Mac 版本

已完成：

1. 增加正式应用图标。
2. 在状态面板上增加下次预计采集、最近错误、位置延迟和每台设备最后更新时间。
3. 增加认证失效、采集异常和通讯权限异常的 macOS 通知。
4. 支持 1–1440 分钟的自定义采集间隔。
5. 清除数据前自动创建加密备份，并支持从 GUI 恢复最近备份。

暂不实施的公开分发工作：Developer ID 正式签名、Apple 公证和自动更新。

### 第二阶段：数据能力

1. 导出 GPX、GeoJSON、CSV。
2. 导出时提供密码加密，避免产生裸坐标文件。
3. 支持按天、设备或行程浏览。
4. 增加停留点、速度、距离和移动时间统计。
5. 过滤定位漂移和异常跳点。
6. 增加正式数据库版本迁移和可浏览的备份管理界面。
7. 支持多轨迹颜色和设备对比。
8. 增加播放、暂停、倍速和时间刻度。

### 第三阶段：安全增强

1. 将 iCloud 会话进一步封装进钥匙串。
2. 使用 Touch ID 解锁地图或导出。
3. 支持主密钥轮换。
4. 清除数据后执行数据库压缩和安全清理。
5. 增加隐私锁屏和坐标模糊显示。
6. 对本地备份实施端到端加密。

### 第四阶段：iPhone/iPad 客户端

推荐采用“Mac 负责采集，iPhone/iPad 负责查看”的架构：

```text
Mac 后台采集
    │
    ├── 本地加密数据库
    │
    └── 端到端加密同步
              │
              ▼
       iPhone / iPad 查看器
```

这是更现实的方案，因为 iOS 不允许普通 App 每隔固定几分钟永久在后台运行，使用私有 Find My 接口也很难进入 App Store。

iPhone/iPad 客户端可以实现：

- 地图查看和轨迹回放。
- 设备筛选和时间筛选。
- 采集状态通知。
- 远程控制 Mac 开始或停止记录。
- 通过 CloudKit 或自建服务同步端到端加密轨迹。
- 本地缓存和离线查看。

如果只做个人侧载版本，也可以尝试直接在 iPhone 上查询，但后台时间不稳定、认证体验更差，而且需要定期重新签名，可靠性低于 Mac 采集方案。

## 总结

当前项目已经是一个能够独立安装和持续运行、具备本地加密、原生地图、详细状态、异常通知、自动备份和数据管理能力的 macOS App。

下一步最值得优先完成的是数据库迁移和可浏览的备份管理，再建立端到端加密同步，最后开发 iPhone/iPad 查看客户端；公开分发前另行完成开发者签名、公证和自动更新。
