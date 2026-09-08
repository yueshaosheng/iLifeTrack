import Darwin
import Foundation

final class BackgroundServiceRunner: @unchecked Sendable {
    private let process = Process()
    private let signalQueue = DispatchQueue(label: "com.ilifetrack.signal-forwarding")
    private let statusMonitor = BackgroundStatusMonitor()
    private var terminationSignal: DispatchSourceSignal?
    private var interruptionSignal: DispatchSourceSignal?

    func run(backend: URL) -> Int32 {
        process.executableURL = backend
        process.arguments = ["run"]
        process.currentDirectoryURL = backend.deletingLastPathComponent()

        signal(SIGTERM, SIG_IGN)
        signal(SIGINT, SIG_IGN)
        let termination = DispatchSource.makeSignalSource(
            signal: SIGTERM,
            queue: signalQueue
        )
        let interruption = DispatchSource.makeSignalSource(
            signal: SIGINT,
            queue: signalQueue
        )
        termination.setEventHandler { [self] in
            guard process.isRunning else { return }
            self.process.terminate()
        }
        interruption.setEventHandler { [self] in
            guard process.isRunning else { return }
            self.process.interrupt()
        }
        termination.resume()
        interruption.resume()
        terminationSignal = termination
        interruptionSignal = interruption
        statusMonitor.start()

        do {
            try process.run()
            process.waitUntilExit()
            statusMonitor.checkNow()
            finishMonitoring()
            if process.terminationStatus != 0 {
                ILifeTrackNotifications.post(
                    identifier: "ilifetrack.background-stopped",
                    title: "iLifeTrack 后台服务已停止",
                    body: "后台组件异常退出，macOS 将尝试重新启动；请打开应用查看状态。"
                )
            }
            return process.terminationStatus
        } catch {
            finishMonitoring()
            ILifeTrackNotifications.post(
                identifier: "ilifetrack.background-start-failed",
                title: "iLifeTrack 后台服务无法启动",
                body: "请重新安装 iLifeTrack 或打开应用检查运行状态。"
            )
            fputs("iLifeTrack background service could not start.\n", stderr)
            return 2
        }
    }

    private func finishMonitoring() {
        terminationSignal?.cancel()
        interruptionSignal?.cancel()
        terminationSignal = nil
        interruptionSignal = nil
        statusMonitor.stop()
    }
}
