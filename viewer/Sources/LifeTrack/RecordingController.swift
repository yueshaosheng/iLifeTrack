import AppKit
import Darwin
import Foundation

@MainActor
final class RecordingController: ObservableObject {
    @Published private(set) var isConfigured = false
    @Published private(set) var isRunning = false
    @Published private(set) var intervalSeconds = 300
    @Published private(set) var retentionDays: Int?
    @Published private(set) var communicationsEnabled = false
    @Published private(set) var selectedDeviceKeys: Set<String> = []
    @Published private(set) var dashboard: DashboardStatus?
    @Published private(set) var isBusy = false
    @Published var message: String?
    @Published var errorMessage: String?

    func refresh() async {
        if let data = try? Data(contentsOf: CLIClient.configURL),
           let config = try? JSONDecoder().decode(LocalConfig.self, from: data)
        {
            isConfigured = true
            intervalSeconds = config.intervalSeconds
            retentionDays = config.retentionDays
            communicationsEnabled = config.communicationsEnabled ?? false
            selectedDeviceKeys = Set(config.selectedDeviceKeys)
        } else {
            isConfigured = false
            selectedDeviceKeys = []
            communicationsEnabled = false
        }
        isRunning = await queryRunningState()
        await refreshDashboard()
    }

    func start() async {
        await perform(success: "后台记录已开始") {
            _ = try await CLIClient.run(["start"])
        }
    }

    func stop() async {
        await perform(success: "后台记录已停止，历史数据已保留") {
            _ = try await CLIClient.run(["stop"])
        }
    }

    func setInterval(_ seconds: Int) async {
        await perform(success: "采集间隔已更新") {
            _ = try await CLIClient.run(["interval", String(seconds)])
        }
    }

    func setRetention(_ days: Int?) async {
        await perform(success: days.map { "已自动保留最近 \($0) 天" } ?? "轨迹将永久保留") {
            _ = try await CLIClient.run(["retention", String(days ?? 0)])
        }
    }

    func applySelection(_ keys: Set<String>) async {
        guard !keys.isEmpty else {
            errorMessage = "请至少选择一台设备。"
            return
        }
        await perform(success: "记录设备已更新") {
            _ = try await CLIClient.run(["select"] + keys.sorted())
        }
    }

    func refreshDevices() async {
        await perform(success: "设备列表已刷新") {
            _ = try await CLIClient.run(["devices"])
        }
    }

    func clearHistory(deviceKey: String?, start: Date?, end: Date?) async {
        var arguments = ["clear-history"]
        if let deviceKey {
            arguments += ["--device-key", deviceKey]
        }
        if let start {
            arguments += ["--start-ms", String(Int64(start.timeIntervalSince1970 * 1_000))]
        }
        if let end {
            arguments += ["--end-ms", String(Int64(end.timeIntervalSince1970 * 1_000))]
        }
        await perform(success: "匹配的历史轨迹已清除，清除前的加密备份已保存") {
            _ = try await CLIClient.run(arguments)
        }
    }

    func setCommunicationsEnabled(_ enabled: Bool) async {
        await perform(
            success: enabled
                ? "通讯归档已启用，只记录从现在开始同步到本机的新内容"
                : "通讯归档已停止，已有本地归档仍然保留"
        ) {
            _ = try await CLIClient.run(["communications", enabled ? "enable" : "disable"])
        }
    }

    func clearCommunications(kind: String?) async {
        var arguments = ["clear-communications"]
        if let kind {
            arguments += ["--kind", kind]
        }
        await perform(success: "匹配的本地通讯归档已清除，清除前的加密备份已保存") {
            _ = try await CLIClient.run(arguments)
        }
    }

    func restoreLatestBackup() async {
        await perform(success: "最近备份已恢复；恢复前的当前数据也已另存为安全备份") {
            _ = try await CLIClient.run(["restore-latest-backup"])
        }
    }

    func importExistingCommunications() async {
        await perform(success: "现有短信和通话记录已导入；重复记录已自动跳过") {
            _ = try await CLIClient.run(["communications", "import"])
        }
    }

    func authenticationCompleted(restartService: Bool) async {
        if restartService {
            await perform(success: "认证已更新，后台位置记录已恢复") {
                _ = try await CLIClient.run(["start"])
            }
        } else {
            await refresh()
        }
    }

    func openFullDiskAccessSettings() {
        guard let url = URL(
            string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
        ) else { return }
        NSWorkspace.shared.open(url)
    }

    private func perform(
        success: String,
        operation: () async throws -> Void
    ) async {
        guard !isBusy else { return }
        isBusy = true
        errorMessage = nil
        do {
            try await operation()
            message = success
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription ?? "操作失败。"
        }
        isBusy = false
        await refresh()
    }

    private func queryRunningState() async -> Bool {
        let domain = "gui/\(getuid())/com.lifetrack.app"
        return (try? await CLIClient.runSystem(
            "/bin/launchctl", arguments: ["print", domain]
        )) != nil
    }

    private func refreshDashboard() async {
        guard let output = try? await CLIClient.run(["gui-status"]),
              let data = output.data(using: .utf8),
              let value = try? JSONDecoder().decode(DashboardStatus.self, from: data)
        else {
            dashboard = nil
            return
        }
        dashboard = value
    }
}
