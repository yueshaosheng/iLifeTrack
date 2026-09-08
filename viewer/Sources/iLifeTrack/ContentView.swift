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

            switch selectedSection {
            case .locations:
                MapBrowserView(store: store, browserState: locationBrowserState)
            case .communications:
                CommunicationArchiveView(store: store, archiveState: communicationArchiveState)
            }
        }
            .toolbar {
                ToolbarItemGroup(placement: .primaryAction) {
                    Label(
                        recording.isRunning ? "正在记录" : "已停止",
                        systemImage: recording.isRunning ? "record.circle.fill" : "stop.circle"
                    )
                    .foregroundStyle(recording.isRunning ? .green : .secondary)

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
                if !recording.isConfigured {
                    showingSettings = true
                }
            }
    }
}

struct MapBrowserView: View {
    @ObservedObject var store: TrackStore
    @ObservedObject var browserState: LocationBrowserState
    @AppStorage("coordinateCorrectionMode") private var coordinateCorrectionRawValue =
        CoordinateCorrectionMode.automatic.rawValue
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

            List(store.devices, selection: $browserState.selectedDeviceKey) { device in
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
                }
                .tag(device.deviceKey)
            }

            Divider()
            Button("重新载入", systemImage: "arrow.clockwise") {
                reload()
            }
            .buttonStyle(.borderless)
            .padding()
        }
        .navigationSplitViewColumnWidth(min: 220, ideal: 260, max: 340)
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
