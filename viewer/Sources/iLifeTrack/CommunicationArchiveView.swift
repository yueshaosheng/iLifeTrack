import Combine
import SwiftUI

enum ArchiveFilter: String, CaseIterable, Identifiable {
    case all = "全部"
    case messages = "短信与信息"
    case calls = "通话"

    var id: String { rawValue }
}

@MainActor
final class CommunicationArchiveState: ObservableObject {
    @Published var filter: ArchiveFilter = .all
    @Published var selectedID: Int64?
    @Published var searchText = ""
    var hasLoadedOnce = false
}

struct CommunicationArchiveView: View {
    @ObservedObject var store: TrackStore
    @ObservedObject var archiveState: CommunicationArchiveState
    private let refreshTimer = Timer.publish(every: 3, on: .main, in: .common).autoconnect()

    private var filter: ArchiveFilter { archiveState.filter }
    private var selectedID: Int64? { archiveState.selectedID }
    private var searchText: String { archiveState.searchText }

    private var filteredEntries: [CommunicationEntry] {
        store.communications.filter { entry in
            let matchesKind = switch filter {
            case .all: true
            case .messages: entry.kind == "message"
            case .calls: entry.kind == "call"
            }
            guard matchesKind else { return false }
            let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !query.isEmpty else { return true }
            return [entry.participantName, entry.participant, entry.body, entry.service]
                .compactMap { $0 }
                .contains { $0.localizedCaseInsensitiveContains(query) }
        }
    }

    private var selectedEntry: CommunicationEntry? {
        filteredEntries.first { $0.id == selectedID } ?? filteredEntries.first
    }

    var body: some View {
        NavigationSplitView {
            VStack(spacing: 0) {
                Picker("类型", selection: $archiveState.filter) {
                    ForEach(ArchiveFilter.allCases) { item in
                        Text(item.rawValue).tag(item)
                    }
                }
                .padding()

                List(filteredEntries, selection: $archiveState.selectedID) { entry in
                    archiveRow(entry)
                        .tag(entry.id)
                }
                .searchable(text: $archiveState.searchText, prompt: "搜索本地归档")

                Divider()
                HStack {
                    Text("\(filteredEntries.count) 条")
                        .foregroundStyle(.secondary)
                    Spacer()
                }
                .padding()
            }
            .navigationSplitViewColumnWidth(min: 280, ideal: 340, max: 440)
        } detail: {
            if let entry = selectedEntry {
                archiveDetail(entry)
            } else {
                ContentUnavailableView(
                    "还没有本地通讯归档",
                    systemImage: "tray",
                    description: Text("请在“设置”中启用通讯归档。只会保存启用后同步到这台 Mac 的新记录。")
                )
            }
        }
        .task {
            store.reload()
            if !archiveState.hasLoadedOnce {
                archiveState.selectedID = filteredEntries.first?.id
                archiveState.hasLoadedOnce = true
            } else if let selectedID,
                      !filteredEntries.contains(where: { $0.id == selectedID }) {
                archiveState.selectedID = filteredEntries.first?.id
            }
        }
        .onReceive(refreshTimer) { _ in
            store.reload()
        }
        .onChange(of: filter) { _, _ in
            archiveState.selectedID = filteredEntries.first?.id
        }
        .onChange(of: searchText) { _, _ in
            archiveState.selectedID = filteredEntries.first?.id
        }
    }

    private func archiveRow(_ entry: CommunicationEntry) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: entry.kind == "message" ? "message.fill" : "phone.fill")
                .foregroundStyle(entry.kind == "message" ? .blue : .green)
                .frame(width: 22)
            VStack(alignment: .leading, spacing: 3) {
                HStack {
                    Text(displayParticipant(entry))
                        .fontWeight(.medium)
                        .lineLimit(1)
                    Spacer()
                    Text(entry.occurredAt.formatted(date: .abbreviated, time: .shortened))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Text(summary(entry))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .padding(.vertical, 3)
    }

    private func archiveDetail(_ entry: CommunicationEntry) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack(spacing: 12) {
                    Image(systemName: entry.kind == "message" ? "message.fill" : "phone.fill")
                        .font(.title2)
                        .foregroundStyle(entry.kind == "message" ? .blue : .green)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(displayParticipant(entry))
                            .font(.title2.bold())
                        Text(entry.kind == "message" ? "短信与信息" : "通话记录")
                            .foregroundStyle(.secondary)
                    }
                }

                Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 10) {
                    detailRow("方向", value: entry.direction == "outgoing" ? "呼出／发出" : "呼入／收到")
                    detailRow(
                        "发生时间",
                        value: entry.occurredAt.formatted(date: .complete, time: .standard)
                    )
                    detailRow(
                        "归档时间",
                        value: entry.archivedAt.formatted(date: .complete, time: .standard)
                    )
                    if let service = entry.service {
                        detailRow("服务", value: service)
                    }
                    if entry.kind == "call" {
                        detailRow("状态", value: callStatus(entry))
                        if let duration = entry.durationSeconds {
                            detailRow("时长", value: durationText(duration))
                        }
                    }
                }

                if entry.kind == "message" {
                    Divider()
                    Text("消息内容")
                        .font(.headline)
                    Text(messageBody(entry))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                Spacer()
            }
            .padding(28)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func detailRow(_ label: String, value: String) -> some View {
        GridRow {
            Text(label)
                .foregroundStyle(.secondary)
            Text(value)
                .textSelection(.enabled)
        }
    }

    private func displayParticipant(_ entry: CommunicationEntry) -> String {
        entry.participantName ?? entry.participant ?? "未知联系人"
    }

    private func summary(_ entry: CommunicationEntry) -> String {
        if entry.kind == "message" {
            return entry.body ?? (entry.hasAttachments ? "附件消息" : "无文本内容")
        }
        return "\(entry.direction == "outgoing" ? "呼出" : "呼入") · \(callStatus(entry))"
    }

    private func messageBody(_ entry: CommunicationEntry) -> String {
        if let body = entry.body { return body }
        return entry.hasAttachments ? "这条记录包含附件；当前版本只归档文字和附件标记。" : "无文本内容"
    }

    private func callStatus(_ entry: CommunicationEntry) -> String {
        guard let answered = entry.answered else { return "未知" }
        return answered ? "已接通" : (entry.direction == "outgoing" ? "未接通" : "未接来电")
    }

    private func durationText(_ seconds: Double) -> String {
        let total = Int(seconds.rounded())
        let minutes = total / 60
        let remainder = total % 60
        return minutes > 0 ? "\(minutes) 分 \(remainder) 秒" : "\(remainder) 秒"
    }
}
