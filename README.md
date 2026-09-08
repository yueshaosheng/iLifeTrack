# iLifeTrack

[English](README_EN.md) · 简体中文

<p align="center">
  <img src="viewer/Resources/AppIcon.svg" width="128" alt="iLifeTrack 图标">
</p>

iLifeTrack 在 Mac 上做两件事：定时保存你个人 Apple 账户中 iPhone、iPad 和 Mac 的位置，形成历史轨迹；把已经通过 iCloud 同步到这台 Mac 的短信、iMessage 和通话记录复制到本地加密档案。

通讯记录一旦归档，之后即使从 iCloud 或其他 Apple 设备中删除，本地副本也不会跟着删除，除非你在 iLifeTrack 中主动清除。

> [!WARNING]
> 项目依赖 Apple 未公开的 iCloud Web 接口，仅适合个人研究和自用。接口可能随时变化，也可能触发限流或重新认证。请勿将其用于救援、防盗或其他安全关键场景。

## 功能

- 记录个人 iPhone、iPad 和 Mac 的位置，长期形成设备历史轨迹。
- 无删除归档短信、iMessage 和通话记录：云端或设备删除不联动删除本地副本。
- 多设备选择，支持 1–1440 分钟采集间隔。
- MapKit 地图、历史轨迹、时间范围筛选和时间轴回看。
- 中国大陆地图坐标偏移自动校正，数据库仍保存原始坐标。
- 本地 AES-256-GCM 加密，主密钥保存在 macOS 钥匙串。
- 后台自动运行、状态面板、异常通知和失败退避。
- 数据清理、保留期限、清理前自动备份和最近备份恢复。

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
./viewer/build-app.sh
open /Applications/iLifeTrack.app
```

脚本会构建 SwiftUI 前端和 PyInstaller 后端，采用本地临时签名，并安装到：

```text
/Applications/iLifeTrack.app
```

当前构建适合本机开发和自用。公开分发仍需要 Developer ID 签名、Hardened Runtime 和 Apple 公证。

## 快速使用

1. 打开 iLifeTrack，进入“记录设置”。
2. 使用 Apple 账户完成认证和双重认证。
3. 选择要记录的设备及采集间隔。
4. 点击“开始记录”。关闭主窗口不会停止后台服务。
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

当前仓库尚未附带开源许可证。在选择许可证前，默认保留所有权利。
