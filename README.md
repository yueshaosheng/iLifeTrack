# iLifeTrack

[English](README_EN.md) · 简体中文

<p align="center">
  <a href="https://github.com/yueshaosheng/iLifeTrack/releases"><img src="https://img.shields.io/github/v/release/yueshaosheng/iLifeTrack?display_name=tag&sort=semver" alt="GitHub Release"></a>
  <a href="https://github.com/yueshaosheng/iLifeTrack/releases"><img src="https://img.shields.io/github/downloads/yueshaosheng/iLifeTrack/total?label=downloads" alt="GitHub Downloads"></a>
  <img src="https://img.shields.io/badge/macOS-14%2B-000000?logo=apple" alt="macOS 14+">
  <img src="https://img.shields.io/badge/Apple%20Silicon-supported-0A84FF?logo=apple" alt="Apple Silicon">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/yueshaosheng/iLifeTrack" alt="MIT License"></a>
</p>

<p align="center">
  <img src="docs/images/AppIcon-README.png" width="128" alt="iLifeTrack 图标">
</p>

iLifeTrack 是一款记录个人 Apple 设备轨迹和通话、短信记录的 macOS 软件。它可以将 Apple“查找”App 中的设备位置信息持续保存，并形成可在地图和时间轴中查看的历史轨迹。

软件还会归档已经同步到这台 Mac 的短信、iMessage 和通话记录。记录一旦归档，即使之后从 iCloud 或 Apple 设备中删除，iLifeTrack 中的本地备份仍然保留，不会跟随删除。

> [!WARNING]
> 项目依赖 Apple 未公开的 iCloud Web 接口，仅适合个人研究和自用。接口可能随时变化，也可能触发限流或重新认证。请勿将其用于救援、防盗或其他安全关键场景。

## 功能

### 位置轨迹

- 记录个人 Apple 账户中 iPhone、iPad 和 Mac 的最后已知位置。
- 可在设置中保存并切换多个 Apple 账户，各账户分别保留设备选择。
- 支持同时选择多台设备，并设置 1–1440 分钟的采集间隔。
- 使用 MapKit 展示历史轨迹，支持时间范围筛选和时间轴回看。
- 自动校正中国大陆地图坐标偏移，同时在数据库中保留原始坐标。

### 通讯归档

- 导入已经同步到 Mac 的短信、iMessage 和通话记录，并持续归档新增记录。
- 云端或设备删除不联动删除已经归档的本地副本。
- 支持按通讯类型和时间筛选，并可搜索号码、联系人及内容。
- 本地归档可以单独清除，不会删除 Apple“信息”或系统通话记录。

### 数据安全与后台运行

- 敏感数据使用 AES-256-GCM 加密，主密钥保存在 macOS 钥匙串。
- 支持后台自动运行、状态查看、异常通知和失败退避。
- 支持数据清理和保留期限设置，清理前自动创建加密备份。
- 支持查看最近备份并从 GUI 恢复。

## 系统要求

- macOS 14 或更高版本。
- Apple Silicon Mac。Intel/Universal 2 尚未支持。
- Apple 账户已启用双重认证。
- 通讯归档需要为 iLifeTrack 授予“完全磁盘访问权限”。

## 从源码构建

需要安装 Xcode Command Line Tools、Swift 6、Python 3.10–3.14 和 [uv](https://docs.astral.sh/uv/)。

```bash
cd iLifeTrack
uv sync --all-extras
./viewer/setup-local-signing.sh
./viewer/build-app.sh
open /Applications/iLifeTrack.app
```

首次构建会创建一个仅供本机使用的长期签名身份。构建脚本会用该身份签名
SwiftUI 前端和 PyInstaller 后端，并安装到：

```text
/Applications/iLifeTrack.app
```

固定签名可让钥匙串和完全磁盘访问权限在本机升级后继续有效。首次迁移到固定签名时，
仍需完成最后一次钥匙串和完全磁盘访问授权。公开分发需要通过
`ILIFETRACK_CODESIGN_IDENTITY` 指定 Developer ID，并完成 Hardened Runtime 和 Apple 公证。

## 快速使用

1. 打开 iLifeTrack，在“设置”中添加 Apple 账户并完成双重认证；需要时可在这里添加或切换其他账户。
2. 回到“位置轨迹”主界面，打开需要持续记录的设备开关。
3. 直接在主界面选择采集间隔。
4. 点击“开始记录”。关闭主窗口不会停止后台服务；退出应用时可选择仅退出界面，或停止后台并退出。
5. 在“位置轨迹”中查看地图和时间轴。
6. 如需通讯归档，先授予完全磁盘访问，再启用归档。

不设置总时长时，记录会持续运行，直到手动停止。Mac 休眠、关机或断网期间无法采集。

## 数据与隐私

运行数据不保存在 Git 仓库中，而是位于：

```text
~/Library/Application Support/iLifeTrack
```

- `history.sqlite3`：加密的轨迹与通讯归档。
- `config.json`：采集设置，不包含密码或明文坐标。
- `sessions/`：本机 iCloud 登录会话。
- `logs/`：后台状态日志，不记录密码、验证码或坐标。

Apple 账户密码和验证码仅通过本机进程管道传递，不写入配置、命令参数或日志。删除 iLifeTrack 的本地通讯副本不会删除 Apple“信息”或系统通话记录。
加密主密钥只由原生应用读取一次并缓存在内存中，再通过匿名进程管道交给后台组件；
不会写入命令参数、配置或日志。

## 项目结构

```text
iLifeTrack/
├── src/ilifetrack/          # Python 采集、认证、加密和数据库
├── viewer/                  # SwiftUI、MapKit 与 macOS 应用打包
├── tests/                   # Python 测试
├── packaging/               # PyInstaller 入口
├── README.md                # 中文说明（默认）
├── README_EN.md             # English documentation
└── PROJECT_SUMMARY.md       # 详细架构与维护说明
```

## 当前限制

- Apple 没有向第三方开放“查找”位置历史 API。
- Apple 返回的是最后已知位置，不是连续 GPS 数据流。
- AirTag/Find My Network 加密报告尚未支持。
- 通讯归档只能读取已经同步到这台 Mac 的本地记录，不保证绝对无遗漏。
- 附件文件尚未复制，只保存文字和附件标记。
- 当前安装包仅支持 Apple Silicon，且尚未正式签名和公证。

## Todo

### 数据能力

- [ ] GPX、GeoJSON 和 CSV 导出。
- [ ] 密码加密的导出与跨 Mac 迁移包。
- [ ] 按天和行程浏览。
- [ ] 停留点、速度、距离与移动时间统计。
- [ ] 异常漂移和跳点过滤。
- [ ] 完整备份浏览与数据库版本迁移。
- [ ] 多设备轨迹对比和自动回放。

### 安全与分发

- [ ] 使用 Touch ID 解锁地图和导出。
- [ ] iCloud 会话加密与主密钥轮换。
- [ ] 隐私锁屏和坐标模糊显示。
- [ ] Developer ID 签名、Apple 公证和自动更新。
- [ ] Universal 2 构建和干净 Mac 安装测试。

### 移动客户端

- [ ] iPhone/iPad 只读查看器。
- [ ] 端到端加密同步和离线缓存。
- [ ] 采集状态通知与 Mac 远程控制。

## 测试

```bash
.venv/bin/pytest
.venv/bin/ruff check src tests
swift test --package-path viewer
```

更完整的架构、数据模型、打包流程和升级路线请参阅 [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)。

## 致谢

iLifeTrack 的实现离不开以下开源项目：

- [iCloudPy](https://github.com/mandarons/icloudpy)：连接 iCloud Web 服务并读取个人设备的最后已知位置。
- [cryptography](https://github.com/pyca/cryptography)：为本地敏感数据提供加密能力。
- [keyring](https://github.com/jaraco/keyring)：安全访问 macOS 钥匙串。
- [PyInstaller](https://github.com/pyinstaller/pyinstaller)：将 Python 后台及其依赖打包进独立 Mac App。
- [python-typedstream](https://github.com/dgelessus/python-typedstream)：解析 macOS 通讯数据库中的 typedstream 数据。

感谢这些项目的维护者和贡献者。

## 许可证

本项目采用 [MIT License](LICENSE)。
