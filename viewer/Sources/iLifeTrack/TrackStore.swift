import CryptoKit
import Foundation
import SQLite3

struct TrackedDevice: Identifiable, Hashable {
    let deviceKey: String
    let name: String
    let deviceType: String
    let lastSeen: Date
    let isAvailable: Bool

    var id: String { deviceKey }
}

struct TrackPoint: Identifiable, Hashable {
    let id: Int64
    let deviceKey: String
    let sourceAt: Date
    let fetchedAt: Date
    let latitude: Double
    let longitude: Double
    let horizontalAccuracy: Double?
    let isOld: Bool?
    let positionType: String?
    let batteryLevel: Double?
}

struct CommunicationEntry: Identifiable, Hashable {
    let id: Int64
    let kind: String
    let occurredAt: Date
    let archivedAt: Date
    let direction: String
    let participant: String?
    let participantName: String?
    let body: String?
    let service: String?
    let durationSeconds: Double?
    let answered: Bool?
    let hasAttachments: Bool
}

enum TrackStoreError: LocalizedError {
    case keyNotFound
    case invalidKey
    case databaseNotFound
    case databaseOpen(String)
    case databaseQuery(String)
    case decrypt

    var errorDescription: String? {
        switch self {
        case .keyNotFound:
            "找不到轨迹加密密钥，请打开“记录设置”完成 Apple 账户认证。"
        case .invalidKey:
            "Keychain 中的轨迹密钥格式无效。"
        case .databaseNotFound:
            "还没有历史数据库，请打开“记录设置”完成认证并开始记录。"
        case let .databaseOpen(message):
            "无法打开历史数据库：\(message)"
        case let .databaseQuery(message):
            "读取历史数据库失败：\(message)"
        case .decrypt:
            "无法解密历史数据。"
        }
    }
}

@MainActor
final class TrackStore: ObservableObject {
    @Published private(set) var devices: [TrackedDevice] = []
    @Published private(set) var points: [TrackPoint] = []
    @Published private(set) var communications: [CommunicationEntry] = []
    @Published private(set) var skippedRecords = 0
    @Published private(set) var skippedPointRecords = 0
    @Published private(set) var lastReloaded: Date?
    @Published var errorMessage: String?

    func reload() {
        do {
            let snapshot = try HistoryReader().load()
            devices = snapshot.devices
            points = snapshot.points
            communications = snapshot.communications
            skippedRecords = snapshot.skippedRecords
            skippedPointRecords = snapshot.skippedPointRecords
            lastReloaded = Date()
            errorMessage = nil
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }
}

private struct HistorySnapshot {
    let devices: [TrackedDevice]
    let points: [TrackPoint]
    let communications: [CommunicationEntry]
    let skippedRecords: Int
    let skippedPointRecords: Int
}

private struct HistoryReader {
    func load() throws -> HistorySnapshot {
        let databaseURL = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/iLifeTrack/history.sqlite3")
        guard FileManager.default.fileExists(atPath: databaseURL.path) else {
            throw TrackStoreError.databaseNotFound
        }

        let masterKey = try MasterKeyStore.shared.loadOrCreate()
        let encryptionKey = deriveEncryptionKey(masterKey)
        var database: OpaquePointer?
        let flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_FULLMUTEX
        guard sqlite3_open_v2(databaseURL.path, &database, flags, nil) == SQLITE_OK,
              let database
        else {
            let message = database.map { String(cString: sqlite3_errmsg($0)) } ?? "unknown"
            if let database { sqlite3_close(database) }
            throw TrackStoreError.databaseOpen(message)
        }
        defer { sqlite3_close(database) }
        sqlite3_busy_timeout(database, 2_000)

        var skippedDevices = 0
        var skippedPoints = 0
        var skippedCommunications = 0
        let devices = try loadDevices(database, encryptionKey, skipped: &skippedDevices)
        let points = try loadPoints(database, encryptionKey, skipped: &skippedPoints)
        let communications = try loadCommunications(
            database, encryptionKey, skipped: &skippedCommunications
        )
        return HistorySnapshot(
            devices: devices,
            points: points,
            communications: communications,
            skippedRecords: skippedDevices + skippedPoints + skippedCommunications,
            skippedPointRecords: skippedPoints
        )
    }

    private func deriveEncryptionKey(_ masterKey: Data) -> SymmetricKey {
        // Stable v1 database-format salt; changing it would make existing history unreadable.
        let formatSalt = Data([
            0x66, 0x69, 0x6e, 0x64, 0x74, 0x72, 0x61, 0x63,
            0x6b, 0x2d, 0x70, 0x6f, 0x63, 0x2d, 0x76, 0x31,
        ])
        let output = HKDF<SHA256>.deriveKey(
            inputKeyMaterial: SymmetricKey(data: masterKey),
            salt: formatSalt,
            info: Data("local-history-keys".utf8),
            outputByteCount: 64
        )
        let bytes = output.withUnsafeBytes { Data($0) }
        return SymmetricKey(data: bytes.prefix(32))
    }

    private func loadDevices(
        _ database: OpaquePointer,
        _ key: SymmetricKey,
        skipped: inout Int
    ) throws -> [TrackedDevice] {
        let availability = columnExists("is_available", table: "devices", database: database)
            ? "is_available" : "1"
        let sql = """
        SELECT device_key, nonce, ciphertext, last_seen_ms, \(availability)
        FROM devices ORDER BY last_seen_ms DESC
        """
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(database, sql, -1, &statement, nil) == SQLITE_OK,
              let statement
        else {
            throw TrackStoreError.databaseQuery(String(cString: sqlite3_errmsg(database)))
        }
        defer { sqlite3_finalize(statement) }

        var devices: [TrackedDevice] = []
        while sqlite3_step(statement) == SQLITE_ROW {
            guard let deviceKey = text(statement, 0),
                  let nonce = blob(statement, 1),
                  let ciphertext = blob(statement, 2)
            else {
                skipped += 1
                continue
            }
            do {
                let payload = try decryptJSON(
                    nonce: nonce,
                    combinedCiphertext: ciphertext,
                    associatedData: Data("device:\(deviceKey)".utf8),
                    key: key
                )
                guard let name = payload["name"] as? String,
                      let deviceType = payload["device_type"] as? String
                else {
                    skipped += 1
                    continue
                }
                let lastSeen = Date(timeIntervalSince1970: Double(sqlite3_column_int64(statement, 3)) / 1000)
                devices.append(
                    TrackedDevice(
                        deviceKey: deviceKey,
                        name: name,
                        deviceType: deviceType,
                        lastSeen: lastSeen,
                        isAvailable: sqlite3_column_int(statement, 4) != 0
                    )
                )
            } catch {
                skipped += 1
            }
        }
        return devices
    }

    private func loadPoints(
        _ database: OpaquePointer,
        _ key: SymmetricKey,
        skipped: inout Int
    ) throws -> [TrackPoint] {
        let sql = """
        SELECT id, device_key, source_at_ms, fetched_at_ms, nonce, ciphertext
        FROM points ORDER BY source_at_ms
        """
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(database, sql, -1, &statement, nil) == SQLITE_OK,
              let statement
        else {
            throw TrackStoreError.databaseQuery(String(cString: sqlite3_errmsg(database)))
        }
        defer { sqlite3_finalize(statement) }

        var points: [TrackPoint] = []
        while sqlite3_step(statement) == SQLITE_ROW {
            let identifier = sqlite3_column_int64(statement, 0)
            guard let deviceKey = text(statement, 1),
                  let nonce = blob(statement, 4),
                  let ciphertext = blob(statement, 5)
            else {
                skipped += 1
                continue
            }
            let sourceAtMS = sqlite3_column_int64(statement, 2)
            let fetchedAtMS = sqlite3_column_int64(statement, 3)
            do {
                let payload = try decryptJSON(
                    nonce: nonce,
                    combinedCiphertext: ciphertext,
                    associatedData: Data("point:\(deviceKey):\(sourceAtMS)".utf8),
                    key: key
                )
                guard let latitude = payload["latitude"] as? Double,
                      let longitude = payload["longitude"] as? Double
                else {
                    skipped += 1
                    continue
                }
                points.append(
                    TrackPoint(
                        id: identifier,
                        deviceKey: deviceKey,
                        sourceAt: Date(timeIntervalSince1970: Double(sourceAtMS) / 1000),
                        fetchedAt: Date(timeIntervalSince1970: Double(fetchedAtMS) / 1000),
                        latitude: latitude,
                        longitude: longitude,
                        horizontalAccuracy: payload["horizontal_accuracy"] as? Double,
                        isOld: payload["is_old"] as? Bool,
                        positionType: payload["position_type"] as? String,
                        batteryLevel: payload["battery_level"] as? Double
                    )
                )
            } catch {
                skipped += 1
            }
        }
        return points
    }

    private func loadCommunications(
        _ database: OpaquePointer,
        _ key: SymmetricKey,
        skipped: inout Int
    ) throws -> [CommunicationEntry] {
        guard tableExists("communications", database: database) else { return [] }
        let sql = """
        SELECT id, kind, record_key, occurred_at_ms, archived_at_ms, nonce, ciphertext
        FROM communications ORDER BY occurred_at_ms DESC
        """
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(database, sql, -1, &statement, nil) == SQLITE_OK,
              let statement
        else {
            throw TrackStoreError.databaseQuery(String(cString: sqlite3_errmsg(database)))
        }
        defer { sqlite3_finalize(statement) }

        var entries: [CommunicationEntry] = []
        while sqlite3_step(statement) == SQLITE_ROW {
            let identifier = sqlite3_column_int64(statement, 0)
            guard let kind = text(statement, 1),
                  let recordKey = text(statement, 2),
                  let nonce = blob(statement, 5),
                  let ciphertext = blob(statement, 6)
            else {
                skipped += 1
                continue
            }
            let occurredAtMS = sqlite3_column_int64(statement, 3)
            let archivedAtMS = sqlite3_column_int64(statement, 4)
            do {
                let payload = try decryptJSON(
                    nonce: nonce,
                    combinedCiphertext: ciphertext,
                    associatedData: Data(
                        "communication:\(recordKey):\(occurredAtMS)".utf8
                    ),
                    key: key
                )
                guard let direction = payload["direction"] as? String else {
                    skipped += 1
                    continue
                }
                entries.append(
                    CommunicationEntry(
                        id: identifier,
                        kind: kind,
                        occurredAt: Date(
                            timeIntervalSince1970: Double(occurredAtMS) / 1_000
                        ),
                        archivedAt: Date(
                            timeIntervalSince1970: Double(archivedAtMS) / 1_000
                        ),
                        direction: direction,
                        participant: payload["participant"] as? String,
                        participantName: payload["participant_name"] as? String,
                        body: payload["body"] as? String,
                        service: payload["service"] as? String,
                        durationSeconds: number(payload["duration_seconds"]),
                        answered: payload["answered"] as? Bool,
                        hasAttachments: payload["has_attachments"] as? Bool ?? false
                    )
                )
            } catch {
                skipped += 1
            }
        }
        return entries
    }

    private func tableExists(_ name: String, database: OpaquePointer) -> Bool {
        let sql = "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1"
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(database, sql, -1, &statement, nil) == SQLITE_OK,
              let statement
        else { return false }
        defer { sqlite3_finalize(statement) }
        let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
        let bindResult = name.withCString { pointer in
            sqlite3_bind_text(statement, 1, pointer, -1, transient)
        }
        guard bindResult == SQLITE_OK else { return false }
        return sqlite3_step(statement) == SQLITE_ROW
    }

    private func columnExists(
        _ name: String, table: String, database: OpaquePointer
    ) -> Bool {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(database, "PRAGMA table_info(\(table))", -1, &statement, nil)
            == SQLITE_OK,
            let statement
        else { return false }
        defer { sqlite3_finalize(statement) }
        while sqlite3_step(statement) == SQLITE_ROW {
            if text(statement, 1) == name { return true }
        }
        return false
    }

    private func number(_ value: Any?) -> Double? {
        (value as? NSNumber)?.doubleValue
    }

    private func decryptJSON(
        nonce: Data,
        combinedCiphertext: Data,
        associatedData: Data,
        key: SymmetricKey
    ) throws -> [String: Any] {
        guard combinedCiphertext.count >= 16 else { throw TrackStoreError.decrypt }
        let ciphertext = combinedCiphertext.dropLast(16)
        let tag = combinedCiphertext.suffix(16)
        let sealedBox = try AES.GCM.SealedBox(
            nonce: AES.GCM.Nonce(data: nonce),
            ciphertext: ciphertext,
            tag: tag
        )
        let plaintext = try AES.GCM.open(sealedBox, using: key, authenticating: associatedData)
        guard let object = try JSONSerialization.jsonObject(with: plaintext) as? [String: Any] else {
            throw TrackStoreError.decrypt
        }
        return object
    }

    private func text(_ statement: OpaquePointer, _ column: Int32) -> String? {
        guard let pointer = sqlite3_column_text(statement, column) else { return nil }
        return String(cString: pointer)
    }

    private func blob(_ statement: OpaquePointer, _ column: Int32) -> Data? {
        let count = Int(sqlite3_column_bytes(statement, column))
        guard count > 0, let pointer = sqlite3_column_blob(statement, column) else { return nil }
        return Data(bytes: pointer, count: count)
    }
}
