import AppKit
import SwiftUI

@MainActor
final class ApplicationDelegate: NSObject, NSApplicationDelegate {
    private var isStoppingBackground = false

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard backgroundServiceIsInstalled else {
            return .terminateNow
        }
        guard !isStoppingBackground else {
            return .terminateLater
        }

        let alert = NSAlert()
        alert.alertStyle = .informational
        alert.messageText = "退出 iLifeTrack？"
        alert.informativeText = "后台仍在记录。你可以只关闭界面，也可以停止后台记录后退出。已有历史数据不会被删除。"
        alert.addButton(withTitle: "仅退出界面")
        alert.addButton(withTitle: "停止后台并退出")
        alert.addButton(withTitle: "取消")

        switch alert.runModal() {
        case .alertFirstButtonReturn:
            return .terminateNow
        case .alertSecondButtonReturn:
            stopBackgroundAndTerminate(sender)
            return .terminateLater
        default:
            return .terminateCancel
        }
    }

    private var backgroundServiceIsInstalled: Bool {
        FileManager.default.fileExists(
            atPath: FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/LaunchAgents/com.ilifetrack.app.plist")
                .path
        )
    }

    private func stopBackgroundAndTerminate(_ sender: NSApplication) {
        isStoppingBackground = true
        Task {
            do {
                _ = try await CLIClient.run(["stop"])
                sender.reply(toApplicationShouldTerminate: true)
            } catch {
                isStoppingBackground = false
                let failure = NSAlert(error: error)
                failure.messageText = "无法停止后台记录"
                failure.informativeText =
                    (error as? LocalizedError)?.errorDescription ?? "请稍后重试。"
                failure.runModal()
                sender.reply(toApplicationShouldTerminate: false)
            }
        }
    }
}

struct ILifeTrackApp: App {
    @NSApplicationDelegateAdaptor(ApplicationDelegate.self) private var applicationDelegate

    init() {
        ILifeTrackNotifications.requestAuthorization()
    }

    var body: some Scene {
        WindowGroup("iLifeTrack") {
            ContentView()
                .frame(minWidth: 920, minHeight: 640)
        }
        .defaultSize(width: 1100, height: 760)
    }
}
