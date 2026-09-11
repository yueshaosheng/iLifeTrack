import MapKit
import Combine
import SwiftUI

enum TimeWindow: String, CaseIterable, Identifiable {
    case oneHour = "1 小时"
    case sixHours = "6 小时"
    case twentyFourHours = "24 小时"
    case fortyEightHours = "48 小时"
    case sevenDays = "7 天"
    case custom = "自定义"
    case all = "全部"

    var id: String { rawValue }

    var cutoff: Date? {
        let seconds: TimeInterval? = switch self {
        case .oneHour: 3_600
        case .sixHours: 6 * 3_600
        case .twentyFourHours: 24 * 3_600
        case .fortyEightHours: 48 * 3_600
        case .sevenDays: 7 * 24 * 3_600
        case .custom, .all: nil
        }
        return seconds.map { Date().addingTimeInterval(-$0) }
    }
}

@MainActor
final class LocationBrowserState: ObservableObject {
    @Published var selectedDeviceKey: String?
    @Published var timeWindow: TimeWindow = .fortyEightHours
    @Published var customStart = Date().addingTimeInterval(-24 * 3_600)
    @Published var customEnd = Date()
    @Published var playbackIndex = 0
    @Published var selectedPointID: Int64?
    @Published var followsLatestPoint = true
    @Published var cameraPosition: MapCameraPosition = .automatic
    var hasLoadedOnce = false
}

struct ContentView: View {
    private enum AppSection: String, CaseIterable, Identifiable {
        case locations = "位置轨迹"
        case communications = "通讯归档"

        var id: String { rawValue }
    }

    @StateObject private var store = TrackStore()
    @StateObject private var recording = RecordingController()
    @StateObject private var locationBrowserState = LocationBrowserState()
    @StateObject private var communicationArchiveState = CommunicationArchiveState()
    @State private var showingSettings = false
    @State private var selectedSection: AppSection = .locations
    @State private var intervalChoice = 300
    @State private var customIntervalMinutes = 5

    var body: some View {
        VStack(spacing: 0) {
            Picker("视图", selection: $selectedSection) {
                ForEach(AppSection.allCases) { section in
                    Text(section.rawValue).tag(section)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 260)
            .padding(8)

            Divider()

            recordingControlBar

            Divider()

            switch selectedSection {
            case .locations:
                MapBrowserView(
                    store: store,
                    recording: recording,
                    browserState: locationBrowserState,
                    onShowAuthentication: { showingSettings = true }
                )
            case .communications:
                CommunicationArchiveView(store: store, archiveState: communicationArchiveState)
            }
        }
            .toolbar {
                ToolbarItemGroup(placement: .primaryAction) {
                    Button("记录设置", systemImage: "slider.horizontal.3") {
                        showingSettings = true
                    }
                }
            }
            .sheet(isPresented: $showingSettings) {
                RecordingSettingsView(store: store, recording: recording)
            }
            .task {
                await recording.refresh()
                syncIntervalControl(recording.intervalSeconds)
                if !recording.isConfigured {
                    showingSettings = true
                }
            }
            .onChange(of: recording.intervalSeconds) { _, newValue in
                syncIntervalControl(newValue)
            }
    }

    private var recordingControlBar: some View {
        HStack(spacing: 12) {
            Label(
                recording.isRunning ? "正在记录" : "已停止",
                systemImage: recording.isRunning ? "record.circle.fill" : "stop.circle"
            )
            .foregroundStyle(recording.isRunning ? .green : .secondary)

            Divider()
                .frame(height: 20)

            Picker("采集间隔", selection: $intervalChoice) {
                Text("1 分钟").tag(60)
                Text("5 分钟（推荐）").tag(300)
                Text("10 分钟").tag(600)
                Text("30 分钟").tag(1_800)
                Text("自定义…").tag(0)
            }
            .pickerStyle(.menu)
            .frame(width: 190)
            .disabled(recording.isBusy)
            .onChange(of: intervalChoice) { _, newValue in
                guard newValue != 0, newValue != recording.intervalSeconds else { return }
                Task {
                    await recording.setInterval(newValue)
                    syncIntervalControl(recording.intervalSeconds)
                }
            }

            if intervalChoice == 0 {
                TextField("分钟", value: $customIntervalMinutes, format: .number)
                    .frame(width: 64)
                    .textFieldStyle(.roundedBorder)
                Stepper(
                    "分钟",
                    value: $customIntervalMinutes,
                    in: 1 ... 1_440
                )
                .labelsHidden()
                Button("应用") {
                    Task {
                        await recording.setInterval(customIntervalMinutes * 60)
                        syncIntervalControl(recording.intervalSeconds)
                    }
                }
                .disabled(
                    recording.isBusy
                        || customIntervalMinutes < 1
                        || customIntervalMinutes > 1_440
                        || customIntervalMinutes * 60 == recording.intervalSeconds
                )
            }

            Spacer(minLength: 8)

            Button("重新读取状态", systemImage: "arrow.clockwise") {
                Task { await recording.refresh() }
            }
            .disabled(recording.isBusy)
            .help("重新读取后台服务、配置、最近采集结果、数据库统计和权限状态；不会向 Apple 请求新位置。")

            if recording.isRunning {
                Button("停止记录", systemImage: "stop.fill", role: .destructive) {
                    Task { await recording.stop() }
                }
                .disabled(recording.isBusy)
            } else {
                Button("开始记录", systemImage: "record.circle") {
                    Task { await recording.start() }
                }
                .buttonStyle(.borderedProminent)
                .disabled(
                    recording.isBusy
                        || (recording.selectedDeviceKeys.isEmpty
                            && !recording.communicationsEnabled)
                )
                .help(
                    recording.selectedDeviceKeys.isEmpty
                        && !recording.communicationsEnabled
                        ? "请先选择至少一台设备，或启用通讯归档。"
                        : "启动后台持续记录"
                )
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }

    private func syncIntervalControl(_ seconds: Int) {
        let presets = [60, 300, 600, 1_800]
        if presets.contains(seconds) {
            intervalChoice = seconds
        } else {
            intervalChoice = 0
            customIntervalMinutes = max(1, seconds / 60)
        }
    }
}

struct MapBrowserView: View {
    @ObservedObject var store: TrackStore
    @ObservedObject var recording: RecordingController
    @ObservedObject var browserState: LocationBrowserState
    let onShowAuthentication: () -> Void
    @AppStorage("coordinateCorrectionMode") private var coordinateCorrectionRawValue =
        CoordinateCorrectionMode.automatic.rawValue
    @State private var showingCancelAuthenticationConfirmation = false
    private let refreshTimer = Timer.publish(every: 3, on: .main, in: .common).autoconnect()

    private var selectedDeviceKey: String? {
        get { browserState.selectedDeviceKey }
        nonmutating set { browserState.selectedDeviceKey = newValue }
    }

    private var timeWindow: TimeWindow {
        get { browserState.timeWindow }
        nonmutating set { browserState.timeWindow = newValue }
    }

    private var customStart: Date {
        get { browserState.customStart }
        nonmutating set { browserState.customStart = newValue }
    }

    private var customEnd: Date {
        get { browserState.customEnd }
        nonmutating set { browserState.customEnd = newValue }
    }

    private var playbackIndex: Int {
        get { browserState.playbackIndex }
        nonmutating set { browserState.playbackIndex = newValue }
    }

    private var selectedPointID: Int64? {
        get { browserState.selectedPointID }
        nonmutating set { browserState.selectedPointID = newValue }
    }

    private var followsLatestPoint: Bool {
        get { browserState.followsLatestPoint }
        nonmutating set { browserState.followsLatestPoint = newValue }
    }

    private var cameraPosition: MapCameraPosition {
        get { browserState.cameraPosition }
        nonmutating set { browserState.cameraPosition = newValue }
    }

    private var coordinateCorrectionMode: CoordinateCorrectionMode {
        CoordinateCorrectionMode(rawValue: coordinateCorrectionRawValue) ?? .automatic
    }

    private var selectedDevice: TrackedDevice? {
        store.devices.first { $0.deviceKey == selectedDeviceKey }
    }

    private var filteredPoints: [TrackPoint] {
        store.points.filter { point in
            guard point.deviceKey == selectedDeviceKey else { return false }
            if timeWindow == .custom {
                return customStart <= customEnd
                    && point.sourceAt >= customStart
                    && point.sourceAt <= customEnd
            }
            return timeWindow.cutoff.map { point.sourceAt >= $0 } ?? true
        }
    }

    private var visiblePoints: [TrackPoint] {
        guard !filteredPoints.isEmpty else { return [] }
        let end = min(max(playbackIndex, 0), filteredPoints.count - 1)
        return Array(filteredPoints.prefix(end + 1))
    }

    private var selectedPoint: TrackPoint? {
        filteredPoints.first { $0.id == selectedPointID } ?? visiblePoints.last
    }

    private var markerPoints: [TrackPoint] {
        guard visiblePoints.count > 250 else { return visiblePoints }
        let step = max(1, visiblePoints.count / 249)
        var reduced = stride(from: 0, to: visiblePoints.count, by: step).map { visiblePoints[$0] }
        if reduced.last?.id != visiblePoints.last?.id, let last = visiblePoints.last {
            reduced.append(last)
        }
        return reduced
    }

    var body: some View {
        NavigationSplitView {
            sidebar
        } detail: {
            detail
        }
        .task {
            if browserState.hasLoadedOnce {
                refreshAutomatically()
            } else {
                reload()
                browserState.hasLoadedOnce = true
            }
        }
        .onReceive(refreshTimer) { _ in
            refreshAutomatically()
        }
        .onChange(of: selectedDeviceKey) { _, _ in
            resetTimelineAndCamera()
        }
        .onChange(of: timeWindow) { _, _ in
            resetTimelineAndCamera()
        }
        .onChange(of: customStart) { _, _ in
            if timeWindow == .custom { resetTimelineAndCamera() }
        }
        .onChange(of: customEnd) { _, _ in
            if timeWindow == .custom { resetTimelineAndCamera() }
        }
        .onChange(of: coordinateCorrectionRawValue) { _, _ in
            resetTimelineAndCamera()
        }
        .alert("取消 Apple 账户认证？", isPresented: $showingCancelAuthenticationConfirmation) {
            Button("保留认证", role: .cancel) {}
            Button("取消认证", role: .destructive) {
                Task {
                    await recording.cancelAuthentication()
                    store.reload()
                }
            }
        } message: {
            Text(
                "本机保存的 Apple 登录会话会被移除，并停止记录设备位置。"
                    + "已有轨迹、通讯归档和加密密钥都会保留。"
            )
        }
    }

    private var sidebar: some View {
        VStack(spacing: 0) {
            Picker("时间范围", selection: $browserState.timeWindow) {
                ForEach(TimeWindow.allCases) { window in
                    Text(window.rawValue).tag(window)
                }
            }
            .padding()

            if timeWindow == .custom {
                VStack(alignment: .leading, spacing: 8) {
                    DatePicker(
                        "开始",
                        selection: $browserState.customStart,
                        displayedComponents: [.date, .hourAndMinute]
                    )
                    DatePicker(
                        "结束",
                        selection: $browserState.customEnd,
                        displayedComponents: [.date, .hourAndMinute]
                    )
                    if customStart > customEnd {
                        Label("开始时间不能晚于结束时间", systemImage: "exclamationmark.triangle.fill")
                            .font(.caption)
                            .foregroundStyle(.red)
                    }
                }
                .datePickerStyle(.field)
                .padding(.horizontal)
                .padding(.bottom, 12)
            }

            Picker("地图坐标", selection: $coordinateCorrectionRawValue) {
                ForEach(CoordinateCorrectionMode.allCases) { mode in
                    Text(mode.title).tag(mode.rawValue)
                }
            }
            .pickerStyle(.menu)
            .padding(.horizontal)
            .padding(.bottom, 8)
            .help("自动校正中国大陆地区的固定地图偏移；数据库仍保存 Apple 返回的原始坐标。")

            List(selection: $browserState.selectedDeviceKey) {
                Section("Apple 账户") {
                    HStack(spacing: 10) {
                        Image(systemName: accountStatusIcon)
                            .foregroundStyle(accountStatusColor)
                            .frame(width: 22)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(accountStatusTitle)
                            if recording.isConfigured {
                                Text(recording.appleID)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }
                        }
                    }

                    if recording.isConfigured {
                        Button("取消认证…", role: .destructive) {
                            showingCancelAuthenticationConfirmation = true
                        }
                        .disabled(recording.isBusy)
                    } else {
                        Button("开始认证…") {
                            onShowAuthentication()
                        }
                    }
                }

                Section("当前“查找”设备") {
                    if availableDevices.isEmpty {
                        Text(recording.isConfigured ? "没有发现可用设备" : "认证后可查看并选择设备")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(availableDevices) { device in
                            deviceRow(device, showsRecordingToggle: true)
                                .tag(device.deviceKey)
                        }
                    }

                    HStack {
                        Button(
                            allAvailableDevicesSelected ? "取消全选" : "全选设备",
                            systemImage: allAvailableDevicesSelected
                                ? "checkmark.circle.fill" : "checkmark.circle"
                        ) {
                            Task {
                                await recording.applySelection(
                                    allAvailableDevicesSelected ? [] : availableDeviceKeys
                                )
                            }
                        }
                        .keyboardShortcut("a", modifiers: [.command, .option])
                        .disabled(availableDevices.isEmpty || recording.isBusy)
                        .help("一键选择或取消所有当前设备（⌥⌘A）")

                        Spacer()

                        Button("刷新设备", systemImage: "arrow.clockwise") {
                            Task {
                                await recording.refreshDevices()
                                store.reload()
                            }
                        }
                        .disabled(!recording.isConfigured || recording.isBusy)
                    }
                }

                if !historicalDevices.isEmpty {
                    Section("历史设备") {
                        ForEach(historicalDevices) { device in
                            deviceRow(device, showsRecordingToggle: false)
                                .tag(device.deviceKey)
                        }
                    }
                }

                if let error = recording.errorMessage {
                    Section {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .font(.caption)
                            .foregroundStyle(.red)
                    }
                }
            }

            Divider()
            Button("重新载入轨迹", systemImage: "arrow.clockwise") {
                reload()
            }
            .buttonStyle(.borderless)
            .padding()
        }
        .navigationSplitViewColumnWidth(min: 220, ideal: 260, max: 340)
    }

    private var availableDevices: [TrackedDevice] {
        store.devices.filter(\.isAvailable)
    }

    private var historicalDevices: [TrackedDevice] {
        store.devices.filter { !$0.isAvailable }
    }

    private var availableDeviceKeys: Set<String> {
        Set(availableDevices.map(\.deviceKey))
    }

    private var allAvailableDevicesSelected: Bool {
        !availableDeviceKeys.isEmpty
            && availableDeviceKeys.isSubset(of: recording.selectedDeviceKeys)
    }

    private var accountNeedsAuthentication: Bool {
        recording.dashboard?.lastPollOutcome == "auth_required"
    }

    private var accountStatusTitle: String {
        if !recording.isConfigured { return "未认证" }
        return accountNeedsAuthentication ? "需要重新认证" : "已认证"
    }

    private var accountStatusIcon: String {
        if !recording.isConfigured { return "person.crop.circle.badge.questionmark" }
        return accountNeedsAuthentication
            ? "person.crop.circle.badge.exclamationmark" : "checkmark.circle.fill"
    }

    private var accountStatusColor: Color {
        if !recording.isConfigured { return .secondary }
        return accountNeedsAuthentication ? .orange : .green
    }

    private func recordingBinding(for deviceKey: String) -> Binding<Bool> {
        Binding(
            get: { recording.selectedDeviceKeys.contains(deviceKey) },
            set: { enabled in
                var selection = recording.selectedDeviceKeys
                if enabled {
                    selection.insert(deviceKey)
                } else {
                    selection.remove(deviceKey)
                }
                Task { await recording.applySelection(selection) }
            }
        )
    }

    private func deviceRow(
        _ device: TrackedDevice,
        showsRecordingToggle: Bool
    ) -> some View {
        HStack(spacing: 10) {
            Image(systemName: iconName(for: device.deviceType))
                .frame(width: 22)
            VStack(alignment: .leading, spacing: 2) {
                Text(device.name)
                    .lineLimit(1)
                Text(device.deviceType)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if !device.isAvailable {
                    Text("已从“查找”移除 · 历史轨迹保留")
                        .font(.caption2)
                        .foregroundStyle(.orange)
                }
            }
            Spacer(minLength: 8)
            if showsRecordingToggle {
                Toggle("记录 \(device.name)", isOn: recordingBinding(for: device.deviceKey))
                    .labelsHidden()
                    .disabled(!recording.isConfigured || recording.isBusy)
                    .help("控制是否持续记录这台设备的位置")
            }
        }
    }

    @ViewBuilder
    private var detail: some View {
        if let errorMessage = store.errorMessage {
            ContentUnavailableView(
                "无法读取轨迹",
                systemImage: "exclamationmark.triangle",
                description: Text(errorMessage)
            )
        } else if store.points.isEmpty && store.skippedPointRecords > 0 {
            ContentUnavailableView(
                "旧轨迹无法解密",
                systemImage: "key.slash",
                description: Text(
                    "数据库中有 \(store.skippedPointRecords) 个位置点使用已经不在钥匙串中的旧密钥加密。"
                )
            )
        } else if selectedDevice == nil {
            ContentUnavailableView("选择一台设备", systemImage: "location")
        } else if filteredPoints.isEmpty {
            ContentUnavailableView(
                "这个时间范围内没有位置",
                systemImage: "map",
                description: Text("离线设备或 Apple 返回的陈旧位置不会生成重复轨迹点。")
            )
        } else {
            VStack(spacing: 0) {
                Map(position: $browserState.cameraPosition) {
                    if visiblePoints.count > 1 {
                        MapPolyline(
                            coordinates: visiblePoints.map {
                                $0.coordinate(using: coordinateCorrectionMode)
                            }
                        )
                            .stroke(.blue, style: StrokeStyle(lineWidth: 4, lineCap: .round, lineJoin: .round))
                    }
                    ForEach(markerPoints) { point in
                        Annotation("", coordinate: point.coordinate(using: coordinateCorrectionMode)) {
                            Button {
                                select(point)
                            } label: {
                                Circle()
                                    .fill(point.id == selectedPoint?.id ? Color.orange : Color.blue)
                                    .stroke(.white, lineWidth: 2)
                                    .frame(width: point.id == selectedPoint?.id ? 16 : 11)
                                    .shadow(radius: 1)
                            }
                            .buttonStyle(.plain)
                            .help(point.sourceAt.formatted(date: .abbreviated, time: .standard))
                        }
                    }
                }
                .mapStyle(.standard(elevation: .realistic))
                .mapControls {
                    MapCompass()
                    MapScaleView()
                }

                timeline
            }
        }
    }

    private var timeline: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(selectedDevice?.name ?? "")
                    .font(.headline)
                Spacer()
                Text("\(filteredPoints.count) 个位置点")
                    .foregroundStyle(.secondary)
            }

            Slider(
                value: Binding(
                    get: { Double(playbackIndex) },
                    set: { value in
                        playbackIndex = Int(value.rounded())
                        selectedPointID = filteredPoints[playbackIndex].id
                        followsLatestPoint = playbackIndex == filteredPoints.count - 1
                    }
                ),
                in: 0 ... Double(max(filteredPoints.count - 1, 1)),
                step: 1
            )
            .disabled(filteredPoints.count < 2)

            if let point = selectedPoint {
                HStack(spacing: 18) {
                    Label(
                        "位置：\(point.sourceAt.formatted(date: .abbreviated, time: .standard))",
                        systemImage: "location.fill"
                    )
                    .help("设备或 Apple 报告的定位时间")
                    Text("采集：\(point.fetchedAt.formatted(date: .abbreviated, time: .standard))")
                        .help("这台 Mac 从 Apple 取回并保存该位置的时间")
                    if let accuracy = point.horizontalAccuracy {
                        Text("精度：±\(accuracy, format: .number.precision(.fractionLength(0))) 米")
                    }
                    if let battery = point.batteryLevel, battery > 0.01 {
                        Text("电量：\(battery * 100, format: .number.precision(.fractionLength(0)))%")
                    }
                    Spacer()
                    if point.isOld == true {
                        Label("Apple 标记为旧位置", systemImage: "clock.badge.exclamationmark")
                            .foregroundStyle(.orange)
                    }
                }
                .font(.callout)
            }
        }
        .padding(14)
        .background(.bar)
    }

    private func reload() {
        store.reload()
        if selectedDeviceKey == nil || !store.devices.contains(where: { $0.deviceKey == selectedDeviceKey }) {
            selectedDeviceKey = store.devices.first(where: { device in
                store.points.contains { $0.deviceKey == device.deviceKey }
            })?.deviceKey ?? store.devices.first?.deviceKey
        }
        resetTimelineAndCamera()
    }

    private func resetTimelineAndCamera() {
        playbackIndex = max(0, filteredPoints.count - 1)
        selectedPointID = filteredPoints.last?.id
        followsLatestPoint = true
        fitCamera(to: filteredPoints)
    }

    private func refreshAutomatically() {
        let previousDeviceKey = selectedDeviceKey
        let previousPointID = selectedPointID
        let previousIndex = playbackIndex

        store.reload()
        if selectedDeviceKey == nil || !store.devices.contains(where: { $0.deviceKey == selectedDeviceKey }) {
            selectedDeviceKey = store.devices.first(where: { device in
                store.points.contains { $0.deviceKey == device.deviceKey }
            })?.deviceKey ?? store.devices.first?.deviceKey
        }

        guard previousDeviceKey == selectedDeviceKey else {
            resetTimelineAndCamera()
            return
        }
        guard !filteredPoints.isEmpty else {
            playbackIndex = 0
            selectedPointID = nil
            return
        }

        if followsLatestPoint {
            playbackIndex = filteredPoints.count - 1
            selectedPointID = filteredPoints.last?.id
        } else if let previousPointID,
                  let refreshedIndex = filteredPoints.firstIndex(where: { $0.id == previousPointID }) {
            playbackIndex = refreshedIndex
            selectedPointID = previousPointID
        } else {
            playbackIndex = min(previousIndex, filteredPoints.count - 1)
            selectedPointID = filteredPoints[playbackIndex].id
        }
    }

    private func select(_ point: TrackPoint) {
        selectedPointID = point.id
        if let index = filteredPoints.firstIndex(where: { $0.id == point.id }) {
            playbackIndex = index
            followsLatestPoint = index == filteredPoints.count - 1
        }
    }

    private func fitCamera(to points: [TrackPoint]) {
        guard let first = points.first else {
            cameraPosition = .automatic
            return
        }
        if points.count == 1 {
            cameraPosition = .region(
                MKCoordinateRegion(
                    center: first.coordinate(using: coordinateCorrectionMode),
                    span: MKCoordinateSpan(latitudeDelta: 0.02, longitudeDelta: 0.02)
                )
            )
            return
        }
        var rectangle = MKMapRect.null
        for point in points {
            let mapPoint = MKMapPoint(point.coordinate(using: coordinateCorrectionMode))
            rectangle = rectangle.union(
                MKMapRect(x: mapPoint.x, y: mapPoint.y, width: 1, height: 1)
            )
        }
        let horizontalPadding = max(rectangle.size.width * 0.15, 500)
        let verticalPadding = max(rectangle.size.height * 0.15, 500)
        cameraPosition = .rect(
            rectangle.insetBy(dx: -horizontalPadding, dy: -verticalPadding)
        )
    }

    private func iconName(for deviceType: String) -> String {
        let lowered = deviceType.lowercased()
        if lowered.contains("iphone") { return "iphone" }
        if lowered.contains("ipad") { return "ipad" }
        if lowered.contains("mac") { return "desktopcomputer" }
        if lowered.contains("airpod") { return "airpodspro" }
        return "location"
    }
}

private extension TrackPoint {
    func coordinate(using correctionMode: CoordinateCorrectionMode) -> CLLocationCoordinate2D {
        CoordinateCorrection.displayCoordinate(
            CLLocationCoordinate2D(latitude: latitude, longitude: longitude),
            mode: correctionMode
        )
    }
}
