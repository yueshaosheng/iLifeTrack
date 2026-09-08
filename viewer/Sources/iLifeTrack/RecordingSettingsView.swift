import SwiftUI

struct RecordingSettingsView: View {
    @ObservedObject var store: TrackStore
    @ObservedObject var recording: RecordingController
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase

    @StateObject private var authentication = AuthenticationController()
    @State private var draftInterval = 300
    @State private var customIntervalMinutes = 5
    @State private var draftRetention = 0
    @State private var showingAuthentication = false
    @State private var showingClearConfirmation = false
    @State private var clearDeviceKey = ""
    @State private var limitClearRange = false
    @State private var clearStart = Date().addingTimeInterval(-30 * 86_400)
    @State private var clearEnd = Date()
    @State private var initializedClearRange = false
    @State private var showingCommunicationClearConfirmation = false
    @State private var communicationClearKind = ""
    @State private var showingRestoreConfirmation = false
    @State private var restartServiceAfterAuthentication = false

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("记录设置")
                        .font(.title2.bold())
                    Text("管理后台记录，不需要打开终端。")
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("完成") { dismiss() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(recording.isBusy)
            }
            .padding(20)

            Divider()

            Form {
                Section("运行状态") {
                    LabeledContent("后台服务") {
                        Label(
                            recording.isRunning ? "正在记录" : "已停止",
                            systemImage: recording.isRunning ? "record.circle.fill" : "stop.circle"
                        )
                        .foregroundStyle(recording.isRunning ? .green : .secondary)
                    }

                    if let dashboard = recording.dashboard {
                        LabeledContent("最近成功") {
                            Text(dateText(dashboard.lastSuccessMS))
                        }
                        LabeledContent("最近一次尝试") {
                            Text(
                                "\(outcomeText(dashboard.lastPollOutcome)) · "
                                    + dateText(dashboard.lastPollFinishedMS)
                            )
                        }
                        LabeledContent("下次预计采集") {
                            if !recording.isRunning {
                                Text("后台已停止")
                            } else if dashboard.lastPollOutcome == "auth_required" {
                                Text("已暂停，等待重新认证")
                                    .foregroundStyle(.orange)
                            } else {
                                Text(dateText(dashboard.nextExpectedPollMS))
                            }
                        }
                        LabeledContent("最新位置延迟") {
                            Text(durationText(dashboard.latestLocationLagSeconds))
                        }
                        if let errorMS = dashboard.lastErrorMS {
                            LabeledContent("最近错误") {
                                VStack(alignment: .trailing, spacing: 2) {
                                    Text(outcomeText(dashboard.lastErrorOutcome))
                                        .foregroundStyle(.orange)
                                    if let detail = dashboard.lastErrorDetail {
                                        Text(errorDetailText(detail))
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                    Text(dateText(errorMS))
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                        LabeledContent("已保存轨迹") {
                            Text("\(dashboard.totalPoints) 个位置点")
                        }
                        if store.skippedPointRecords > 0 {
                            Label(
                                "其中 \(store.skippedPointRecords) 个旧位置点无法用当前钥匙串密钥解密",
                                systemImage: "key.slash"
                            )
                            .font(.caption)
                            .foregroundStyle(.orange)
                        }
                        if dashboard.historyStartMS != nil {
                            LabeledContent("历史范围") {
                                Text(
                                    "\(dateText(dashboard.historyStartMS)) — "
                                        + dateText(dashboard.historyEndMS)
                                )
                            }
                        }
                        if !dashboard.deviceStatuses.isEmpty {
                            Divider()
                            ForEach(dashboard.deviceStatuses) { status in
                                LabeledContent(deviceName(for: status.deviceKey)) {
                                    VStack(alignment: .trailing, spacing: 2) {
                                        Text(dateText(status.lastLocationMS))
                                        Text("延迟 \(durationText(status.locationLagSeconds))")
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                            }
                        }
                    }

                    HStack {
                        Button("刷新状态", systemImage: "arrow.clockwise") {
                            Task { await recording.refresh() }
                        }
                        Spacer()
                        if recording.isRunning {
                            Button("停止记录", role: .destructive) {
                                Task { await recording.stop() }
                            }
                        } else {
                            Button("开始记录") {
                                Task { await recording.start() }
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(
                                recording.isBusy
                                    || (recording.selectedDeviceKeys.isEmpty
                                        && !recording.communicationsEnabled)
                            )
                        }
                    }
                }

                Section("采集设置") {

                    Picker("采集间隔", selection: $draftInterval) {
                        Text("1 分钟").tag(60)
                        Text("5 分钟（推荐）").tag(300)
                        Text("10 分钟").tag(600)
                        Text("30 分钟").tag(1_800)
                        Text("自定义…").tag(0)
                    }

                    if draftInterval == 0 {
                        HStack {
                            TextField(
                                "分钟",
                                value: $customIntervalMinutes,
                                format: .number
                            )
                            .frame(width: 90)
                            .textFieldStyle(.roundedBorder)
                            Stepper(
                                "分钟（1–1440）",
                                value: $customIntervalMinutes,
                                in: 1 ... 1_440
                            )
                        }
                    }

                    HStack {
                        Button("应用间隔") {
                            Task { await recording.setInterval(effectiveIntervalSeconds) }
                        }
                        .disabled(
                            recording.isBusy
                                || customIntervalMinutes < 1
                                || customIntervalMinutes > 1_440
                                || effectiveIntervalSeconds == recording.intervalSeconds
                        )

                        Spacer()
                    }
                }

                Section("Apple 账户") {
                    HStack {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(recording.isConfigured ? "认证信息已配置" : "尚未认证")
                            Text("密码和验证码只交给本机认证进程，不会写入配置文件。")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button(recording.isConfigured ? "重新认证…" : "开始认证…") {
                            authentication.reset()
                            restartServiceAfterAuthentication = recording.isRunning
                            showingAuthentication = true
                        }
                    }
                }

                Section("通讯归档") {
                    LabeledContent("归档状态") {
                        Label(
                            recording.communicationsEnabled ? "正在监视" : "未启用",
                            systemImage: recording.communicationsEnabled
                                ? "archivebox.fill" : "archivebox"
                        )
                        .foregroundStyle(
                            recording.communicationsEnabled ? .green : .secondary
                        )
                    }

                    LabeledContent("完全磁盘访问") {
                        let granted = recording.dashboard?.fullDiskAccessGranted == true
                        Label(
                            granted ? "已授权" : "未授权",
                            systemImage: granted
                                ? "checkmark.shield.fill" : "exclamationmark.shield.fill"
                        )
                        .foregroundStyle(granted ? .green : .orange)
                    }

                    if let dashboard = recording.dashboard {
                        LabeledContent("已归档") {
                            Text(
                                "\(dashboard.messageCount) 条消息 · "
                                    + "\(dashboard.callCount) 条通话"
                            )
                        }
                        LabeledContent("最近扫描") {
                            Text(
                                "\(communicationOutcomeText(dashboard.lastCommunicationOutcome)) · "
                                    + dateText(dashboard.lastCommunicationScanMS)
                            )
                        }
                    }

                    Text(
                        "首次启用会导入当前已同步到这台 Mac 的短信、iMessage 和通话记录，"
                            + "之后持续归档新记录。"
                            + "文字、号码和姓名使用现有密钥加密；附件文件暂不复制。"
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)

                    if recording.dashboard?.fullDiskAccessGranted != true {
                        Text(
                            "首次使用：在“隐私与安全性 → 完全磁盘访问权限”中加入 iLifeTrack "
                                + "并打开开关，然后返回本应用。"
                        )
                        .font(.caption)
                        .foregroundStyle(.orange)
                    }

                    HStack {
                        if recording.dashboard?.fullDiskAccessGranted != true {
                            Button("打开完全磁盘访问设置") {
                                recording.openFullDiskAccessSettings()
                            }
                        }
                        if recording.communicationsEnabled {
                            Button("导入现有记录") {
                                Task {
                                    await recording.importExistingCommunications()
                                    store.reload()
                                }
                            }
                            .disabled(recording.isBusy)
                        }
                        Spacer()
                        Button(
                            recording.communicationsEnabled ? "停止通讯归档" : "启用通讯归档…",
                            role: recording.communicationsEnabled ? .destructive : nil
                        ) {
                            Task {
                                await recording.setCommunicationsEnabled(
                                    !recording.communicationsEnabled
                                )
                                store.reload()
                            }
                        }
                        .disabled(recording.isBusy)
                    }

                    if (recording.dashboard?.totalCommunications ?? 0) > 0 {
                        Divider()
                        Picker("清除归档", selection: $communicationClearKind) {
                            Text("全部通讯").tag("")
                            Text("仅短信与信息").tag("message")
                            Text("仅通话").tag("call")
                        }
                        HStack {
                            Text("只影响 iLifeTrack 本地归档，不会删除 Apple“信息”或通话历史。")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Spacer()
                            Button("清除通讯归档…", role: .destructive) {
                                showingCommunicationClearConfirmation = true
                            }
                        }
                    }
                }

                Section("位置历史数据") {
                    if let dashboard = recording.dashboard {
                        LabeledContent("轨迹数量", value: "\(dashboard.totalPoints) 个位置点")
                        LabeledContent(
                            "本地占用",
                            value: ByteCountFormatter.string(
                                fromByteCount: dashboard.databaseBytes,
                                countStyle: .file
                            )
                        )
                    }

                    Picker("自动保留", selection: $draftRetention) {
                        Text("永久保留").tag(0)
                        Text("最近 30 天").tag(30)
                        Text("最近 90 天").tag(90)
                        Text("最近 1 年").tag(365)
                    }
                    HStack {
                        Text("超过期限的数据会在下一次采集时自动清理。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer()
                        Button("应用保留期限") {
                            Task {
                                await recording.setRetention(draftRetention == 0 ? nil : draftRetention)
                            }
                        }
                        .disabled(
                            recording.isBusy || draftRetention == (recording.retentionDays ?? 0)
                        )
                    }

                    Divider()

                    if let backup = recording.dashboard?.latestBackup {
                        LabeledContent("自动加密备份") {
                            VStack(alignment: .trailing, spacing: 2) {
                                Text(dateText(backup.createdAtMS))
                                Text(
                                    "\(recording.dashboard?.backupCount ?? 0) 个 · "
                                        + ByteCountFormatter.string(
                                            fromByteCount: backup.sizeBytes,
                                            countStyle: .file
                                        )
                                )
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            }
                        }
                        HStack {
                            Text("清除前自动保存整库快照，最多保留 20 个。")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Spacer()
                            Button("恢复最近备份…") {
                                showingRestoreConfirmation = true
                            }
                            .disabled(recording.isBusy)
                        }
                    } else {
                        LabeledContent("自动加密备份", value: "尚无备份")
                    }

                    Divider()

                    Picker("清除设备", selection: $clearDeviceKey) {
                        Text("全部设备").tag("")
                        ForEach(store.devices) { device in
                            Text(device.name).tag(device.deviceKey)
                        }
                    }
                    Toggle("限定位置时间范围", isOn: $limitClearRange)
                    if limitClearRange {
                        DatePicker(
                            "开始",
                            selection: $clearStart,
                            displayedComponents: [.date, .hourAndMinute]
                        )
                        DatePicker(
                            "结束",
                            selection: $clearEnd,
                            displayedComponents: [.date, .hourAndMinute]
                        )
                        if clearStart > clearEnd {
                            Label("开始时间不能晚于结束时间", systemImage: "exclamationmark.triangle.fill")
                                .font(.caption)
                                .foregroundStyle(.red)
                        }
                    }

                    HStack {
                        Text("认证、设备选择和后台设置不会被删除。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer()
                        Button(clearButtonTitle, role: .destructive) {
                            showingClearConfirmation = true
                        }
                        .disabled(
                            (recording.dashboard?.totalPoints ?? 0) == 0
                                || recording.isBusy
                                || (limitClearRange && clearStart > clearEnd)
                        )
                    }
                }

                if let message = recording.message {
                    Section {
                        Label(message, systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                    }
                }
                if let error = recording.errorMessage {
                    Section {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.red)
                    }
                }
            }
            .formStyle(.grouped)
        }
        .frame(width: 680, height: 760)
        .overlay {
            if recording.isBusy {
                ProgressView()
                    .padding(18)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
            }
        }
        .sheet(isPresented: $showingAuthentication) {
            AuthenticationView(controller: authentication) {
                showingAuthentication = false
                Task {
                    await recording.authenticationCompleted(
                        restartService: restartServiceAfterAuthentication
                    )
                    store.reload()
                    syncDrafts()
                }
            }
        }
        .task {
            await recording.refresh()
            store.reload()
            syncDrafts()
        }
        .onChange(of: recording.intervalSeconds) { _, newValue in
            syncIntervalDraft(newValue)
        }
        .onChange(of: recording.retentionDays) { _, newValue in
            draftRetention = newValue ?? 0
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .active {
                Task { await recording.refresh() }
            }
        }
        .alert("永久清除匹配的轨迹？", isPresented: $showingClearConfirmation) {
            Button("取消", role: .cancel) {}
            Button("永久清除", role: .destructive) {
                Task {
                    await recording.clearHistory(
                        deviceKey: clearDeviceKey.isEmpty ? nil : clearDeviceKey,
                        start: limitClearRange ? clearStart : nil,
                        end: limitClearRange ? clearEnd : nil
                    )
                    store.reload()
                }
            }
        } message: {
            Text(clearConfirmationMessage)
        }
        .alert(
            "永久清除本地通讯归档？",
            isPresented: $showingCommunicationClearConfirmation
        ) {
            Button("取消", role: .cancel) {}
            Button("永久清除", role: .destructive) {
                Task {
                    await recording.clearCommunications(
                        kind: communicationClearKind.isEmpty ? nil : communicationClearKind
                    )
                    store.reload()
                }
            }
        } message: {
            Text("这不会删除 Apple“信息”或通话历史。iLifeTrack 会先创建加密备份，可从数据管理中恢复。")
        }
        .alert("恢复最近的加密备份？", isPresented: $showingRestoreConfirmation) {
            Button("取消", role: .cancel) {}
            Button("恢复") {
                Task {
                    await recording.restoreLatestBackup()
                    store.reload()
                }
            }
        } message: {
            Text("整个 iLifeTrack 数据库将回到备份时的状态。恢复后新增的轨迹和通讯会被替换，但恢复前会再创建一个安全备份。")
        }
    }

    private func syncDrafts() {
        syncIntervalDraft(recording.intervalSeconds)
        draftRetention = recording.retentionDays ?? 0
        if !initializedClearRange, let dashboard = recording.dashboard {
            clearStart = dashboard.historyStartMS.map { date(from: $0) }
                ?? Date().addingTimeInterval(-30 * 86_400)
            clearEnd = dashboard.historyEndMS.map { date(from: $0) } ?? Date()
            initializedClearRange = true
        }
    }

    private var effectiveIntervalSeconds: Int {
        draftInterval == 0 ? customIntervalMinutes * 60 : draftInterval
    }

    private func syncIntervalDraft(_ seconds: Int) {
        let presets = [60, 300, 600, 1_800]
        if presets.contains(seconds) {
            draftInterval = seconds
        } else {
            draftInterval = 0
            customIntervalMinutes = max(1, seconds / 60)
        }
    }

    private func deviceName(for deviceKey: String) -> String {
        store.devices.first { $0.deviceKey == deviceKey }?.name
            ?? recording.dashboard?.deviceStatuses.first {
                $0.deviceKey == deviceKey
            }?.deviceName
            ?? "旧轨迹设备（名称无法解密）"
    }

    private var clearButtonTitle: String {
        clearDeviceKey.isEmpty && !limitClearRange ? "清除全部记录…" : "清除匹配记录…"
    }

    private var clearConfirmationMessage: String {
        let device = clearDeviceKey.isEmpty
            ? "全部设备"
            : (store.devices.first { $0.deviceKey == clearDeviceKey }?.name ?? "所选设备")
        let range = limitClearRange
            ? "\(clearStart.formatted(date: .abbreviated, time: .shortened))至"
                + clearEnd.formatted(date: .abbreviated, time: .shortened)
            : "全部时间"
        return "将删除\(device)在\(range)内的轨迹。iLifeTrack 会先创建加密备份；后台运行时，新位置仍会继续保存。"
    }

    private func date(from milliseconds: Int64) -> Date {
        Date(timeIntervalSince1970: Double(milliseconds) / 1_000)
    }

    private func dateText(_ milliseconds: Int64?) -> String {
        guard let milliseconds else { return "暂无" }
        return date(from: milliseconds).formatted(date: .abbreviated, time: .standard)
    }

    private func durationText(_ seconds: Int64?) -> String {
        guard let seconds else { return "暂无" }
        if seconds < 60 { return "\(seconds) 秒" }
        if seconds < 3_600 { return "\(seconds / 60) 分钟" }
        let hours = seconds / 3_600
        let minutes = seconds % 3_600 / 60
        return minutes == 0 ? "\(hours) 小时" : "\(hours) 小时 \(minutes) 分钟"
    }

    private func outcomeText(_ outcome: String?) -> String {
        switch outcome {
        case "success": "成功"
        case "network_error": "网络错误"
        case "auth_required": "需要重新认证"
        case "provider_error": "Apple 接口错误"
        case "internal_error": "内部错误"
        case "no_selection": "未选择设备"
        default: "暂无"
        }
    }

    private func communicationOutcomeText(_ outcome: String?) -> String {
        switch outcome {
        case "success": "正常"
        case "permission_required": "需要完全磁盘访问权限"
        case "internal_error": "扫描错误"
        default: recording.communicationsEnabled ? "等待首次扫描" : "未启用"
        }
    }

    private func errorDetailText(_ detail: String) -> String {
        switch detail {
        case "reauthenticate": "Apple 会话已失效"
        case "network": "网络连接不可用"
        case "select_devices_first": "尚未选择记录设备"
        default: detail
        }
    }
}

private struct AuthenticationView: View {
    @ObservedObject var controller: AuthenticationController
    let onFinished: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var appleID = ""
    @State private var password = ""
    @State private var verificationCode = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Apple 账户认证")
                .font(.title2.bold())

            switch controller.phase {
            case .credentials, .failed:
                credentialsForm
            case .submittingCredentials:
                waitingView("正在联系 Apple…")
            case let .verificationCode(pushSent, invalidCode):
                verificationForm(pushSent: pushSent, invalidCode: invalidCode)
            case .submittingCode:
                waitingView("正在验证…")
            case let .authenticated(deviceCount):
                authenticatedView(deviceCount: deviceCount)
            }
        }
        .padding(24)
        .frame(width: 470)
        .interactiveDismissDisabled(isSubmitting)
        .onDisappear {
            password = ""
            verificationCode = ""
            if !isAuthenticated { controller.reset() }
        }
    }

    private var credentialsForm: some View {
        Group {
            TextField("Apple 账户", text: $appleID)
                .textContentType(.username)
            SecureField("Apple 账户密码", text: $password)
                .textContentType(.password)

            if case let .failed(message) = controller.phase {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
            }

            HStack {
                Button("取消") { dismiss() }
                Spacer()
                Button("继续") {
                    let secret = password
                    password = ""
                    controller.begin(appleID: appleID, password: secret)
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(appleID.trimmingCharacters(in: .whitespaces).isEmpty || password.isEmpty)
            }
        }
    }

    private func verificationForm(pushSent: Bool, invalidCode: Bool) -> some View {
        Group {
            Label(
                pushSent ? "验证码请求已发送到受信任设备。" : "请使用短信或受信任设备上的验证码。",
                systemImage: "lock.shield"
            )
            Text("只在这里输入六位验证码。不要把验证码发到聊天或保存到文件。")
                .font(.callout)
                .foregroundStyle(.secondary)
            if invalidCode {
                Label("验证码不正确，请输入新验证码。", systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
            }
            SecureField("六位验证码", text: $verificationCode)
                .textContentType(.oneTimeCode)

            HStack {
                Button("取消") { dismiss() }
                Spacer()
                Button("验证") {
                    let code = verificationCode
                    verificationCode = ""
                    controller.submit(code: code)
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(verificationCode.count != 6)
            }
        }
    }

    private func waitingView(_ message: String) -> some View {
        HStack(spacing: 12) {
            ProgressView()
            Text(message)
        }
        .frame(maxWidth: .infinity, minHeight: 110)
    }

    private func authenticatedView(deviceCount: Int) -> some View {
        Group {
            Label("认证成功", systemImage: "checkmark.circle.fill")
                .font(.title3.bold())
                .foregroundStyle(.green)
            Text("已读取 \(deviceCount) 台设备。现在可以选择设备并开始后台记录。")
                .foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("完成") { onFinished() }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
            }
        }
    }

    private var isSubmitting: Bool {
        controller.phase == .submittingCredentials || controller.phase == .submittingCode
    }

    private var isAuthenticated: Bool {
        if case .authenticated = controller.phase { return true }
        return false
    }
}
