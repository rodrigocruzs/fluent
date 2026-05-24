import Cocoa
import UserNotifications

class AppDelegate: NSObject, NSApplicationDelegate {

    private var reportWindowController: ReportWindowController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        setupMenu()

        UNUserNotificationCenter.current().delegate = self
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }

        DarwinNotificationBridge.shared.startListening(name: "com.fluent.reportReady") { [weak self] in
            self?.showLatestReport()
        }

        showReport()
    }

    // MARK: - Engine launch

// MARK: - Menu

    private func setupMenu() {
        let mainMenu = NSMenu()
        let appMenuItem = NSMenuItem()
        mainMenu.addItem(appMenuItem)
        let appMenu = NSMenu()
        appMenuItem.submenu = appMenu
        appMenu.addItem(NSMenuItem(title: "Quit Fluent", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        NSApp.mainMenu = mainMenu
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if !hasVisibleWindows { showReport() }
        return true
    }

    // MARK: - Window

    private func showReport() {
        if reportWindowController == nil {
            reportWindowController = ReportWindowController()
        }
        NSApp.activate(ignoringOtherApps: true)
        reportWindowController?.showWindow(nil)
        reportWindowController?.window?.makeKeyAndOrderFront(nil)
        reportWindowController?.window?.orderFrontRegardless()
    }

    private func showLatestReport() {
        showReport()
        if let jsonString = loadLatestJSONString() {
            reportWindowController?.loadReportJSON(jsonString)
        }
    }

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
