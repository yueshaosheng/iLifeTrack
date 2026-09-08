import Foundation

struct AuthBridgeResponse: Decodable, Sendable {
    let event: String
    let pushSent: Bool?
    let reason: String?
    let diagnosticCode: String?
    let deviceCount: Int?

    enum CodingKeys: String, CodingKey {
        case event
        case pushSent = "push_sent"
        case reason
        case diagnosticCode = "diagnostic_code"
        case deviceCount = "device_count"
    }
}

final class AuthBridgeSession: @unchecked Sendable {
    private let process = Process()
    private let inputPipe = Pipe()
    private let outputPipe = Pipe()

    func begin(appleID: String, password: String) throws -> AuthBridgeResponse {
        let executable = CLIClient.executableURL
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw CLIClientError.executableMissing
        }
        process.executableURL = executable
        process.arguments = ["gui-auth-bridge"]
        process.currentDirectoryURL = CLIClient.workingDirectory
        process.standardInput = inputPipe
        process.standardOutput = outputPipe
        process.standardError = FileHandle.nullDevice
        try process.run()
        try send([
            "action": "begin",
            "apple_id": appleID,
            "password": password,
            "master_key": try MasterKeyStore.shared.encodedKey(),
        ])
        return try readResponse()
    }

    func submit(code: String) throws -> AuthBridgeResponse {
        try send(["action": "submit_code", "code": code])
        return try readResponse()
    }

    func cancel() {
        try? send(["action": "cancel"])
        if process.isRunning { process.terminate() }
    }

    private func send(_ payload: [String: String]) throws {
        var data = try JSONSerialization.data(withJSONObject: payload)
        data.append(0x0A)
        try inputPipe.fileHandleForWriting.write(contentsOf: data)
    }

    private func readResponse() throws -> AuthBridgeResponse {
        var data = Data()
        while true {
            guard let byte = try outputPipe.fileHandleForReading.read(upToCount: 1),
                  !byte.isEmpty
            else {
                throw CLIClientError.invalidResponse
            }
            if byte[0] == 0x0A { break }
            data.append(byte)
        }
        return try JSONDecoder().decode(AuthBridgeResponse.self, from: data)
    }
}

@MainActor
final class AuthenticationController: ObservableObject {
    enum Phase: Equatable {
        case credentials
        case submittingCredentials
        case verificationCode(pushSent: Bool, invalidCode: Bool)
        case submittingCode
        case authenticated(deviceCount: Int)
        case failed(String)
    }

    @Published private(set) var phase: Phase = .credentials
    private var session: AuthBridgeSession?

    func begin(appleID: String, password: String) {
        guard !appleID.trimmingCharacters(in: .whitespaces).isEmpty, !password.isEmpty else {
            phase = .failed("请输入 Apple 账户和密码。")
            return
        }
        phase = .submittingCredentials
        let newSession = AuthBridgeSession()
        session = newSession
        Task {
            do {
                let response = try await Task.detached {
                    try newSession.begin(appleID: appleID, password: password)
                }.value
                handle(response)
            } catch {
                phase = .failed("登录失败，请检查账户、密码和网络。")
                session = nil
            }
        }
    }

    func submit(code: String) {
        guard code.count == 6, code.allSatisfy(\.isNumber), let session else {
            phase = .failed("请输入六位验证码。")
            return
        }
        phase = .submittingCode
        Task {
            do {
                let response = try await Task.detached {
                    try session.submit(code: code)
                }.value
                handle(response)
            } catch {
                phase = .failed("验证码提交失败，请重新认证。")
                self.session = nil
            }
        }
    }

    func reset() {
        session?.cancel()
        session = nil
        phase = .credentials
    }

    private func handle(_ response: AuthBridgeResponse) {
        switch response.event {
        case "2fa_required":
            phase = .verificationCode(pushSent: response.pushSent == true, invalidCode: false)
        case "invalid_code":
            phase = .verificationCode(pushSent: true, invalidCode: true)
        case "authenticated":
            phase = .authenticated(deviceCount: response.deviceCount ?? 0)
            session = nil
        case "error":
            let baseMessage = message(for: response.reason)
            if let code = response.diagnosticCode, !code.isEmpty {
                phase = .failed("\(baseMessage)\n诊断码：\(code)")
            } else {
                phase = .failed(baseMessage)
            }
            session = nil
        default:
            phase = .failed("认证服务返回了未知状态。")
            session = nil
        }
    }

    private func message(for reason: String?) -> String {
        switch reason {
        case "missing_credentials": "请输入 Apple 账户和密码。"
        case "credentials_rejected": "Apple 拒绝了这次网页登录。这不一定表示密码错误，也可能是临时风险控制或登录接口限制。"
        case "network_error": "无法连接 Apple 服务。请检查网络后重试。"
        case "find_my_session_rejected": "Apple 账户已登录，但“查找”服务未接受新会话。请先确认 iCloud.com 中的“查找”可以正常打开，再重试。"
        case "verification_failed": "验证码验证时 Apple 服务返回错误，请重新认证。"
        case "apple_service_error": "Apple 服务返回了无法处理的响应，请稍后重试。"
        case "too_many_invalid_codes": "验证码错误次数过多，请重新认证。"
        case "legacy_2sa_not_supported": "这个账户使用旧版两步验证，当前 GUI 暂不支持。"
        case "trust_failed": "Apple 未能信任本次登录，请稍后重试。"
        case "cancelled": "认证已取消。"
        default: "认证失败，请检查账户、密码和网络。"
        }
    }
}
