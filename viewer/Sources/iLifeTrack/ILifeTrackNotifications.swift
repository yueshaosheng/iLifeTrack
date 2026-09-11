import CryptoKit
import Foundation
import SQLite3
import UserNotifications

enum ILifeTrackNotifications {
    static func requestAuthorization() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    static func post(identifier: String, title: String, body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        let request = UNNotificationRequest(
            identifier: identifier,
            content: content,
            trigger: nil
        )
        UNUserNotificationCenter.current().add(request)
    }

    static func pollMessage(outcome: String) -> (title: String, body: String)? {
        switch outcome {
        case "auth_required":
            ("iLifeTrack 需要重新认证", "Apple 账户会话已失效，请打开 iLifeTrack 完成认证。")
        case "network_error":
            ("iLifeTrack 暂时无法联网", "位置采集遇到网络错误，后台将自动延迟重试。")
        case "provider_error":
            ("iLifeTrack 无法读取位置", "Apple 位置接口返回异常，后台将自动重试。")
        case "internal_error":
            ("iLifeTrack 后台发生错误", "位置采集遇到内部错误，请打开应用查看运行状态。")
        case "no_selection":
            ("iLifeTrack 没有记录设备", "请打开应用并至少选择一台需要记录的设备。")
        default:
            nil
        }
    }

    static func communicationMessage(outcome: String) -> (title: String, body: String)? {
        switch outcome {
        case "permission_required":
            (
                "iLifeTrack 无法读取通讯记录",
                "请在系统设置中为 iLifeTrack 开启完全磁盘访问权限。"
            )
        case "internal_error":
            ("iLifeTrack 通讯归档异常", "请打开应用查看通讯归档运行状态。")
        default:
            nil
        }
    }
}

private struct BackgroundStatusSnapshot {
    var pollID: Int64 = 0
    var pollOutcome: String?
    var communicationScanMS: Int64 = 0
    var communicationOutcome: String?
}

final class BackgroundStatusMonitor: @unchecked Sendable {
    private let dataRoot: URL
    private let queue = DispatchQueue(label: "com.ilifetrack.status-monitor")
    private var timer: DispatchSourceTimer?
    private var previous = BackgroundStatusSnapshot()

    init() {
        dataRoot = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/iLifeTrack")
    }

    func start() {
        queue.sync {
            previous = readSnapshot()
            let source = DispatchSource.makeTimerSource(queue: queue)
            source.schedule(deadline: .now() + 2, repeating: 5)
            source.setEventHandler { [weak self] in
                self?.checkForNewFailures()
            }
            source.resume()
            timer = source
        }
    }

    func checkNow() {
        queue.sync {
            checkForNewFailures()
        }
    }

    func stop() {
        queue.sync {
            timer?.cancel()
            timer = nil
        }
    }

    private func checkForNewFailures() {
        let current = readSnapshot()
        if current.pollID > previous.pollID,
           current.pollOutcome != previous.pollOutcome,
           let outcome = current.pollOutcome,
           let message = ILifeTrackNotifications.pollMessage(outcome: outcome)
        {
            ILifeTrackNotifications.post(
                identifier: "ilifetrack.poll.\(outcome)",
                title: message.title,
                body: message.body
            )
        }
        if current.communicationScanMS > previous.communicationScanMS,
           current.communicationOutcome != previous.communicationOutcome,
           let outcome = current.communicationOutcome,
           let message = ILifeTrackNotifications.communicationMessage(outcome: outcome)
        {
            ILifeTrackNotifications.post(
                identifier: "ilifetrack.communication.\(outcome)",
                title: message.title,
                body: message.body
            )
        }
        previous = current
    }

    private func readSnapshot() -> BackgroundStatusSnapshot {
        let paths = currentDatabasePaths()
        var snapshot = previous
        if let locationPath = paths.location {
            readDatabase(locationPath) { connection in
                if let row = queryOne(
                    connection,
                    sql: "SELECT id, outcome FROM poll_runs ORDER BY id DESC LIMIT 1"
                ) {
                    snapshot.pollID = row.integer
                    snapshot.pollOutcome = row.text
                }
            }
        }
        readDatabase(paths.communications) { connection in
            if let row = queryOne(
                connection,
                sql: "SELECT scanned_at_ms, outcome FROM communication_status WHERE id=1"
            ) {
                snapshot.communicationScanMS = row.integer
                snapshot.communicationOutcome = row.text
            }
        }
        return snapshot
    }

    private func readDatabase(
        _ databasePath: String,
        operation: (OpaquePointer) -> Void
    ) {
        var connection: OpaquePointer?
        guard sqlite3_open_v2(
            databasePath,
            &connection,
            SQLITE_OPEN_READONLY | SQLITE_OPEN_FULLMUTEX,
            nil
        ) == SQLITE_OK, let connection else {
            if connection != nil { sqlite3_close(connection) }
            return
        }
        defer { sqlite3_close(connection) }
        operation(connection)
    }

    private func currentDatabasePaths() -> (location: String?, communications: String) {
        let legacyURL = dataRoot.appendingPathComponent("history.sqlite3")
        guard let data = try? Data(contentsOf: CLIClient.configURL),
              let config = try? JSONDecoder().decode(LocalConfig.self, from: data)
        else {
            return (nil, dataRoot.appendingPathComponent("communications.sqlite3").path)
        }
        let appleID = config.appleID.trimmingCharacters(in: .whitespacesAndNewlines)
        let legacyAccountID = config.legacyDatabaseAccountID ?? ""
        let legacyDatabaseExists = FileManager.default.fileExists(atPath: legacyURL.path)
        let usesLegacyDatabase = legacyDatabaseExists && (
            legacyAccountID.isEmpty || accountStorageID(appleID) == legacyAccountID
        )
        let location: String? = if appleID.isEmpty {
            nil
        } else if usesLegacyDatabase {
            legacyURL.path
        } else {
            dataRoot.appendingPathComponent("accounts")
                .appendingPathComponent(accountStorageID(appleID))
                .appendingPathComponent("history.sqlite3").path
        }
        let communications = legacyDatabaseExists
            ? legacyURL.path
            : dataRoot.appendingPathComponent("communications.sqlite3").path
        return (location, communications)
    }

    private func accountStorageID(_ appleID: String) -> String {
        SHA256.hash(data: Data(appleID.lowercased().utf8))
            .prefix(16)
            .map { String(format: "%02x", $0) }
            .joined()
    }

    private func queryOne(
        _ connection: OpaquePointer,
        sql: String
    ) -> (integer: Int64, text: String?)? {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(connection, sql, -1, &statement, nil) == SQLITE_OK,
              let statement
        else { return nil }
        defer { sqlite3_finalize(statement) }
        guard sqlite3_step(statement) == SQLITE_ROW else { return nil }
        let text = sqlite3_column_text(statement, 1).map { String(cString: $0) }
        return (sqlite3_column_int64(statement, 0), text)
    }
}
