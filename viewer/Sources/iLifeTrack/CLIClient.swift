import Foundation

enum CLIClientError: LocalizedError {
    case executableMissing
    case commandFailed(String)
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .executableMissing:
            "找不到 iLifeTrack 后端，请重新构建应用。"
        case let .commandFailed(message):
            message.isEmpty ? "操作失败，请稍后重试。" : message
        case .invalidResponse:
            "iLifeTrack 后端返回了无法识别的响应。"
        }
    }
}

enum CLIClient {
    static var executableURL: URL {
        if let resources = Bundle.main.resourceURL {
            let bundled = resources
                .appendingPathComponent("backend/ilifetrack/ilifetrack")
            if FileManager.default.isExecutableFile(atPath: bundled.path) {
                return bundled
            }
        }
        let projectRoot = Bundle.main.bundleURL
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        return projectRoot.appendingPathComponent(".venv/bin/ilifetrack")
    }

    static var workingDirectory: URL {
        executableURL.deletingLastPathComponent()
    }

    static var configURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/iLifeTrack/config.json")
    }

    static func run(_ arguments: [String]) async throws -> String {
        let masterKey = try MasterKeyStore.shared.encodedKey()
        return try await Task.detached(priority: .userInitiated) {
            try runSynchronously(
                executable: executableURL,
                arguments: ["--master-key-stdin"] + arguments,
                standardInput: masterKey + "\n"
            )
        }.value
    }

    static func runWithoutMasterKey(_ arguments: [String]) async throws -> String {
        try await Task.detached(priority: .userInitiated) {
            try runSynchronously(executable: executableURL, arguments: arguments)
        }.value
    }

    static func runSystem(_ executable: String, arguments: [String]) async throws -> String {
        try await Task.detached(priority: .utility) {
            try runSynchronously(
                executable: URL(fileURLWithPath: executable), arguments: arguments
            )
        }.value
    }

    private static func runSynchronously(
        executable: URL, arguments: [String], standardInput: String? = nil
    ) throws -> String {
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw CLIClientError.executableMissing
        }
        let outputPipe = Pipe()
        let errorPipe = Pipe()
        let inputPipe = standardInput == nil ? nil : Pipe()
        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        process.currentDirectoryURL = workingDirectory
        process.standardOutput = outputPipe
        process.standardError = errorPipe
        process.standardInput = inputPipe
        try process.run()
        if let standardInput, let inputPipe {
            inputPipe.fileHandleForWriting.write(Data(standardInput.utf8))
            try? inputPipe.fileHandleForWriting.close()
        }
        process.waitUntilExit()

        let output = outputPipe.fileHandleForReading.readDataToEndOfFile()
        let error = errorPipe.fileHandleForReading.readDataToEndOfFile()
        let outputText = String(decoding: output, as: UTF8.self)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if process.terminationStatus != 0 {
            let errorText = String(decoding: error, as: UTF8.self)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            throw CLIClientError.commandFailed(String(errorText.suffix(240)))
        }
        return outputText
    }
}

struct LocalConfig: Decodable {
    let appleID: String
    let selectedDeviceKeys: [String]
    let intervalSeconds: Int
    let retentionDays: Int?
    let communicationsEnabled: Bool?

    enum CodingKeys: String, CodingKey {
        case appleID = "apple_id"
        case selectedDeviceKeys = "selected_device_keys"
        case intervalSeconds = "interval_seconds"
        case retentionDays = "retention_days"
        case communicationsEnabled = "communications_enabled"
    }
}

struct DashboardStatus: Decodable, Sendable {
    let totalPoints: Int
    let historyStartMS: Int64?
    let historyEndMS: Int64?
    let lastPollStartedMS: Int64?
    let lastPollFinishedMS: Int64?
    let lastPollOutcome: String?
    let lastPollDetail: String?
    let lastSuccessMS: Int64?
    let lastErrorMS: Int64?
    let lastErrorOutcome: String?
    let lastErrorDetail: String?
    let nextExpectedPollMS: Int64?
    let latestLocationLagSeconds: Int64?
    let deviceStatuses: [DeviceRecordingStatus]
    let databaseBytes: Int64
    let communicationsEnabled: Bool
    let fullDiskAccessGranted: Bool
    let totalCommunications: Int
    let messageCount: Int
    let callCount: Int
    let lastCommunicationArchivedMS: Int64?
    let lastCommunicationScanMS: Int64?
    let lastCommunicationOutcome: String?
    let backupCount: Int
    let latestBackup: BackupStatus?

    enum CodingKeys: String, CodingKey {
        case totalPoints = "total_points"
        case historyStartMS = "history_start_ms"
        case historyEndMS = "history_end_ms"
        case lastPollStartedMS = "last_poll_started_ms"
        case lastPollFinishedMS = "last_poll_finished_ms"
        case lastPollOutcome = "last_poll_outcome"
        case lastPollDetail = "last_poll_detail"
        case lastSuccessMS = "last_success_ms"
        case lastErrorMS = "last_error_ms"
        case lastErrorOutcome = "last_error_outcome"
        case lastErrorDetail = "last_error_detail"
        case nextExpectedPollMS = "next_expected_poll_ms"
        case latestLocationLagSeconds = "latest_location_lag_seconds"
        case deviceStatuses = "device_statuses"
        case databaseBytes = "database_bytes"
        case communicationsEnabled = "communications_enabled"
        case fullDiskAccessGranted = "full_disk_access_granted"
        case totalCommunications = "total_communications"
        case messageCount = "message_count"
        case callCount = "call_count"
        case lastCommunicationArchivedMS = "last_communication_archived_ms"
        case lastCommunicationScanMS = "last_communication_scan_ms"
        case lastCommunicationOutcome = "last_communication_outcome"
        case backupCount = "backup_count"
        case latestBackup = "latest_backup"
    }
}

struct BackupStatus: Decodable, Sendable {
    let name: String
    let createdAtMS: Int64
    let sizeBytes: Int64

    enum CodingKeys: String, CodingKey {
        case name
        case createdAtMS = "created_at_ms"
        case sizeBytes = "size_bytes"
    }
}

struct DeviceRecordingStatus: Decodable, Sendable, Identifiable {
    let deviceKey: String
    let deviceName: String?
    let lastLocationMS: Int64
    let lastFetchedMS: Int64
    let locationLagSeconds: Int64

    var id: String { deviceKey }

    enum CodingKeys: String, CodingKey {
        case deviceKey = "device_key"
        case deviceName = "device_name"
        case lastLocationMS = "last_location_ms"
        case lastFetchedMS = "last_fetched_ms"
        case locationLagSeconds = "location_lag_seconds"
    }
}
