# iLifeTrack

English · [简体中文](README.md)

<p align="center">
  <a href="https://github.com/yueshaosheng/iLifeTrack/releases"><img src="https://img.shields.io/github/v/release/yueshaosheng/iLifeTrack?display_name=tag&sort=semver" alt="GitHub Release"></a>
  <a href="https://github.com/yueshaosheng/iLifeTrack/releases"><img src="https://img.shields.io/github/downloads/yueshaosheng/iLifeTrack/total?label=downloads" alt="GitHub Downloads"></a>
  <img src="https://img.shields.io/badge/macOS-14%2B-000000?logo=apple" alt="macOS 14+">
  <img src="https://img.shields.io/badge/Apple%20Silicon-supported-0A84FF?logo=apple" alt="Apple Silicon">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/yueshaosheng/iLifeTrack" alt="MIT License"></a>
</p>

<p align="center">
  <img src="docs/images/AppIcon-README.png" width="128" alt="iLifeTrack icon">
</p>

iLifeTrack is a macOS app for recording the location history and call and message records of your personal Apple devices. It continuously saves device locations from Apple's Find My app and turns them into historical tracks that you can view on a map and timeline.

It also archives messages, iMessages, and call records that have already synced to this Mac. Once a record is archived, deleting it from iCloud or an Apple device does not remove the local backup in iLifeTrack.

> [!WARNING]
> This project relies on an undocumented Apple iCloud web interface and is intended for personal research and use. The interface may change, trigger rate limits, or require re-authentication. Do not use iLifeTrack for rescue, theft protection, or any safety-critical purpose.

## Features

### Location history

- Records the last known locations of iPhone, iPad, and Mac devices in your personal Apple Account.
- Saves and switches between multiple Apple Accounts in Settings, with separate device selections for each account.
- Supports multiple devices and polling intervals from 1 to 1,440 minutes.
- Uses MapKit to display historical tracks with time-range filters and timeline playback.
- Corrects the mainland China map offset for display while retaining original coordinates in the database.

### Communications archive

- Imports messages, iMessages, and call records already synced to the Mac, then continues archiving new records.
- Cloud or device deletion does not remove records already saved in the local archive.
- Supports filtering by type and time, plus searches across numbers, contacts, and content.
- Local archives can be cleared independently without deleting Apple Messages or system call history.

### Data security and background operation

- Encrypts sensitive data with AES-256-GCM; the master key stays in macOS Keychain.
- Runs in the background with status reporting, notifications, and retry backoff.
- Supports retention rules and selective deletion, with an automatic encrypted backup before cleanup.
- Shows the latest backup and supports restoration from the GUI.

## Requirements

- macOS 14 or later.
- An Apple Silicon Mac. Intel and Universal 2 builds are not yet supported.
- An Apple Account with two-factor authentication enabled.
- Full Disk Access for iLifeTrack when communications archiving is enabled.

## Build from source

Install Xcode Command Line Tools, Swift 6, Python 3.10–3.14, and [uv](https://docs.astral.sh/uv/).

```bash
cd iLifeTrack
uv sync --all-extras
./viewer/setup-local-signing.sh
./viewer/build-app.sh
open /Applications/iLifeTrack.app
```

The first build creates a persistent signing identity for this Mac. The build script signs the SwiftUI frontend and PyInstaller backend with that identity, then installs the app at:

```text
/Applications/iLifeTrack.app
```

The stable identity lets Keychain and Full Disk Access authorization survive local upgrades. The first migration to stable signing still requires one final Keychain and Full Disk Access authorization. Public distribution requires a Developer ID selected through `ILIFETRACK_CODESIGN_IDENTITY`, Hardened Runtime, and Apple notarization.

## Quick start

1. Open iLifeTrack, add an Apple Account in **Settings**, and complete two-factor authentication. Add or switch accounts there when needed.
2. Return to **Location History** and enable the devices you want to record continuously.
3. Choose a polling interval directly in the main window.
4. Select **Start Recording**. Closing the main window does not stop the background service; when quitting the app, choose whether to leave recording active or stop it before exiting.
5. Use **Location History** to inspect the map and timeline.
6. To archive communications, grant Full Disk Access before enabling the archive.

With no total duration configured, recording continues until you stop it manually. Collection cannot run while the Mac is asleep, powered off, or offline.

## Data and privacy

Runtime data is excluded from the Git repository and stored at:

```text
~/Library/Application Support/iLifeTrack
```

- `accounts/<account-id>/history.sqlite3`: a separate encrypted location database for each Apple Account.
- `communications.sqlite3`: the shared local communications archive, independent of the Find My account.
- When upgrading, the existing `history.sqlite3` remains the original account's location database and the shared communications archive, so no history is copied or lost. Other accounts still use separate databases.
- `config.json`: collection settings; no password or plaintext coordinates.
- `sessions/`: the local iCloud login session.
- `logs/`: background status logs; no passwords, verification codes, or coordinates.

Apple Account passwords and verification codes pass only through a local process pipe. They are not written to configuration, command arguments, or logs. Deleting an iLifeTrack archive does not delete data from Apple Messages or the system call history.
The native app reads the encryption master key once, keeps it in memory, and passes it to the backend through an anonymous process pipe. The key is never written to command arguments, configuration, or logs.

## Repository layout

```text
iLifeTrack/
├── src/ilifetrack/          # Python collection, authentication, crypto, and storage
├── viewer/                  # SwiftUI, MapKit, and macOS app packaging
├── tests/                   # Python tests
├── packaging/               # PyInstaller entry point
├── README.md                # Chinese documentation (default)
├── README_EN.md             # English documentation
└── PROJECT_SUMMARY.md       # Architecture and maintenance notes
```

## Limitations

- Apple does not provide a public third-party API for Find My location history.
- Locations are last-known updates, not a continuous GPS stream.
- AirTag and encrypted Find My Network reports are not supported.
- Communications archiving only sees records already synced to this Mac and cannot guarantee zero loss.
- Attachment files are not copied; only message text and attachment presence are stored.
- The current build is Apple Silicon-only and is not Developer ID-signed or notarized.

## Todo

### Data

- [ ] GPX, GeoJSON, and CSV export.
- [ ] Password-encrypted exports and portable Mac-to-Mac backups.
- [ ] Day and trip-based browsing.
- [ ] Stay-point, speed, distance, and movement-time statistics.
- [ ] Location drift and outlier filtering.
- [ ] Full backup browser and database schema migrations.
- [ ] Multi-device comparison and automatic timeline playback.

### Security and distribution

- [ ] Touch ID protection for maps and exports.
- [ ] Encrypted iCloud sessions and master-key rotation.
- [ ] Privacy lock and blurred-coordinate display.
- [ ] Developer ID signing, Apple notarization, and automatic updates.
- [ ] Universal 2 builds and clean-Mac installation testing.

### Mobile

- [ ] A read-only iPhone and iPad viewer.
- [ ] End-to-end encrypted sync and offline caching.
- [ ] Collection-status notifications and remote Mac controls.

## Tests

```bash
.venv/bin/pytest
.venv/bin/ruff check src tests
swift test --package-path viewer
```

See [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) for detailed architecture, storage, packaging, and roadmap notes.

## Acknowledgements

iLifeTrack is made possible by these open-source projects:

- [iCloudPy](https://github.com/mandarons/icloudpy) — connects to iCloud web services and reads the last known locations of personal devices.
- [cryptography](https://github.com/pyca/cryptography) — provides encryption for sensitive local data.
- [keyring](https://github.com/jaraco/keyring) — provides secure access to macOS Keychain.
- [PyInstaller](https://github.com/pyinstaller/pyinstaller) — packages the Python backend and its dependencies inside the standalone Mac app.
- [python-typedstream](https://github.com/dgelessus/python-typedstream) — decodes typedstream data found in macOS communications databases.

Thank you to their maintainers and contributors.

## License

iLifeTrack is available under the [MIT License](LICENSE).
