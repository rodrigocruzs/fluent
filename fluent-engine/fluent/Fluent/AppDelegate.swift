import Cocoa
import UserNotifications

@main
class AppDelegate: NSObject, NSApplicationDelegate {

    private var reportWindowController: ReportWindowController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        UNUserNotificationCenter.current().delegate = self
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }

        // Listen for Darwin notification from Python engine
        DarwinNotificationBridge.shared.startListening(name: "com.fluent.reportReady") { [weak self] in
            self?.showLatestReport()
        }

        showReport()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if !hasVisibleWindows { showReport() }
        return true
    }

    private func showReport() {
        if reportWindowController == nil {
            reportWindowController = ReportWindowController()
        }
        reportWindowController?.showWindow(nil)
        reportWindowController?.window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    /// Called when a new report is ready (Darwin notification). Opens the report detail immediately.
    private func showLatestReport() {
        showReport()
        if let jsonString = loadLatestJSONString() {
            reportWindowController?.loadReportJSON(jsonString)
        }
    }

    /// Read latest.json and return it as a raw JSON string (Sendable-safe).
    private func loadLatestJSONString() -> String? {
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".fluent/reports/latest.json")
        guard let data = try? Data(contentsOf: url) else { return nil }
        return String(data: data, encoding: .utf8)
    }
}

extension AppDelegate: UNUserNotificationCenterDelegate {
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler handler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        handler([.banner, .sound])
    }
}
