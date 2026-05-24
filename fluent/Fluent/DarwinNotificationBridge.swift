import Foundation

/// Bridges Darwin (system-wide) notifications to Swift closures.
/// Python signals the report is ready with: notifyutil -p com.fluent.reportReady
@MainActor
final class DarwinNotificationBridge {
    static let shared = DarwinNotificationBridge()
    private var handlers: [String: () -> Void] = [:]
    private init() {}

    func startListening(name: String, handler: @escaping @MainActor () -> Void) {
        handlers[name] = handler

        let center = CFNotificationCenterGetDarwinNotifyCenter()
        let nameRef = name as CFString

        // Use a global context key (the name string itself) to route callbacks
        // without capturing self in a C closure.
        let key = name
        CFNotificationCenterAddObserver(
            center,
            nil,
            { _, _, name, _, _ in
                guard let cfName = name else { return }
                let notifName = cfName.rawValue as String
                DispatchQueue.main.async {
                    DarwinNotificationBridge.shared.handlers[notifName]?()
                }
            },
            nameRef,
            nil,
            .deliverImmediately
        )
        _ = key // suppress unused warning
    }
}
