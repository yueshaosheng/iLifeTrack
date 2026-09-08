import Foundation
import Security

enum MasterKeyStoreError: LocalizedError {
    case keychain(OSStatus)
    case invalidKey
    case randomGeneration(OSStatus)

    var errorDescription: String? {
        switch self {
        case let .keychain(status):
            "无法访问 iLifeTrack 钥匙串密钥（\(status)）。"
        case .invalidKey:
            "钥匙串中的 iLifeTrack 密钥格式无效。"
        case let .randomGeneration(status):
            "无法生成 iLifeTrack 加密密钥（\(status)）。"
        }
    }
}

/// The native app is the only component allowed to read the Keychain item.
/// The value is cached for the lifetime of each process and passed to the
/// bundled backend through an anonymous stdin pipe.
final class MasterKeyStore: @unchecked Sendable {
    static let shared = MasterKeyStore()

    private let service = "com.ilifetrack.app"
    private let account = "history-master-key-v1"
    private let lock = NSLock()
    private var cachedKey: Data?

    private init() {}

    func loadOrCreate() throws -> Data {
        lock.lock()
        defer { lock.unlock() }
        if let cachedKey { return cachedKey }

        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecReturnData: true,
            kSecMatchLimit: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        let key: Data
        if status == errSecSuccess {
            guard let encodedData = result as? Data,
                  let encoded = String(data: encodedData, encoding: .utf8),
                  let decoded = Self.decode(encoded), decoded.count == 32
            else {
                throw MasterKeyStoreError.invalidKey
            }
            key = decoded
        } else if status == errSecItemNotFound {
            var bytes = [UInt8](repeating: 0, count: 32)
            let randomStatus = bytes.withUnsafeMutableBytes { buffer in
                SecRandomCopyBytes(kSecRandomDefault, buffer.count, buffer.baseAddress!)
            }
            guard randomStatus == errSecSuccess else {
                throw MasterKeyStoreError.randomGeneration(randomStatus)
            }
            key = Data(bytes)
            let encodedData = Data(Self.encode(key).utf8)
            let addQuery: [CFString: Any] = [
                kSecClass: kSecClassGenericPassword,
                kSecAttrService: service,
                kSecAttrAccount: account,
                kSecAttrAccessible: kSecAttrAccessibleAfterFirstUnlock,
                kSecValueData: encodedData,
            ]
            let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
            guard addStatus == errSecSuccess else {
                throw MasterKeyStoreError.keychain(addStatus)
            }
        } else {
            throw MasterKeyStoreError.keychain(status)
        }

        cachedKey = key
        return key
    }

    func encodedKey() throws -> String {
        Self.encode(try loadOrCreate())
    }

    private static func encode(_ key: Data) -> String {
        key.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
    }

    private static func decode(_ encoded: String) -> Data? {
        var standard = encoded
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let remainder = standard.count % 4
        if remainder != 0 {
            standard += String(repeating: "=", count: 4 - remainder)
        }
        return Data(base64Encoded: standard)
    }
}
