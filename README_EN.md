# iLifeTrack

English · [简体中文](README.md)

<p align="center">
  <img src="viewer/Resources/AppIcon.svg" width="128" alt="iLifeTrack icon">
</p>

iLifeTrack does two things on your Mac: it periodically saves the locations of the iPhone, iPad, and Mac devices in your personal Apple Account to build a location history; and it copies messages, iMessages, and call records already synced through iCloud to this Mac into an encrypted local archive.

Once a communications record has been archived, deleting it from iCloud or another Apple device does not delete the local copy. It remains available until you explicitly remove it in iLifeTrack.

> [!WARNING]
> This project relies on an undocumented Apple iCloud web interface and is intended for personal research and use. The interface may change, trigger rate limits, or require re-authentication. Do not use iLifeTrack for rescue, theft protection, or any safety-critical purpose.

## Features

- Records personal iPhone, iPad, and Mac locations to build a long-term device history.
- Keeps a deletion-independent archive of messages, iMessages, and calls: cloud or device deletion does not remove the local copy.
- Supports multiple devices and polling intervals from 1 to 1,440 minutes.
- Includes a MapKit map, history filters, tracks, and timeline playback.
- Corrects the mainland China map offset for display while retaining original coordinates.
- Encrypts local content with AES-256-GCM; the master key stays in macOS Keychain.
- Runs in the background with status reporting, notifications, and retry backoff.
- Supports retention rules, selective deletion, automatic backups, and latest-backup restore.

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
./viewer/build-app.sh
open /Applications/iLifeTrack.app
```

The script builds the SwiftUI frontend and the PyInstaller backend, applies an ad-hoc local signature, and installs the app at:

```text
/Applications/iLifeTrack.app
```

The current build is intended for local development and personal use. Public distribution still requires Developer ID signing, Hardened Runtime, and Apple notarization.

## Quick start

1. Open iLifeTrack and select **Recording Settings**.
2. Authenticate with your Apple Account and complete two-factor authentication.
3. Select devices and a polling interval.
4. Select **Start Recording**. Closing the main window does not stop the background service.
5. Use **Location History** to inspect the map and timeline.
6. To archive communications, grant Full Disk Access before enabling the archive.

With no total duration configured, recording continues until you stop it manually. Collection cannot run while the Mac is asleep, powered off, or offline.

## Data and privacy

Runtime data is excluded from the Git repository and stored at:

```text
~/Library/Application Support/iLifeTrack
```

- `history.sqlite3`: encrypted location and communications history.
- `config.json`: collection settings; no password or plaintext coordinates.
- `sessions/`: the local iCloud login session.
- `logs/`: background status logs; no passwords, verification codes, or coordinates.

Apple Account passwords and verification codes pass only through a local process pipe. They are not written to configuration, command arguments, or logs. Deleting an iLifeTrack archive does not delete data from Apple Messages or the system call history.

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

No open-source license has been selected yet. All rights are reserved until a license is added.
