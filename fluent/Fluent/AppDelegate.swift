import Cocoa
import UserNotifications
import AVFoundation

class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate, @unchecked Sendable {

    private var reportWindowController: ReportWindowController?
    private var engineSetupProcess: Process?
    private var engineProcess: Process?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        setupMenu()

        UNUserNotificationCenter.current().delegate = self
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }

        DarwinNotificationBridge.shared.startListening(name: "com.fluent.reportReady") { [weak self] in
            DispatchQueue.main.async { self?.showLatestReport() }
        }

        requestMicrophonePermission()
        setupEngineIfNeeded()
        showReport()
    }

    // MARK: - Microphone permission

    private func requestMicrophonePermission() {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            break
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .audio) { _ in }
        default:
            break
        }
    }

    // MARK: - Engine setup & launch

    private func setupEngineIfNeeded() {
        let sentinel = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".fluent/engine/venv/bin/python3")

        if FileManager.default.fileExists(atPath: sentinel.path) {
            startEngine()
            return
        }

        guard
            let engineSrc = Bundle.main.resourceURL?.appendingPathComponent("engine"),
            let setupScript = Bundle.main.path(forResource: "setup_engine", ofType: "sh", inDirectory: "engine")
        else {
            print("[Fluent] setup_engine.sh not found in bundle — skipping engine setup")
            return
        }

        print("[Fluent] First launch — running engine setup...")
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [setupScript, engineSrc.path]
        process.terminationHandler = { [self] p in
            let status = p.terminationStatus
            DispatchQueue.main.async {
                if status == 0 {
                    print("[Fluent] Engine setup complete.")
                    self.startEngine()
                } else {
                    print("[Fluent] Engine setup failed (status \(status)). Check ~/.fluent/engine-setup.log")
                }
            }
        }
        try? process.run()
        engineSetupProcess = process
    }

    private func startEngine() {
        // Kill any existing engine process
        engineProcess?.terminate()
        engineProcess = nil

        // Prefer the venv python (set up by setup_engine.sh), fall back to system Python
        let venvPython = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".fluent/engine/venv/bin/python3").path
        let systemPython = "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
        let pythonPath = FileManager.default.fileExists(atPath: venvPython) ? venvPython : systemPython

        // Find main.py: prefer bundled engine, fall back to repo location
        let bundledMain = Bundle.main.resourceURL?
            .appendingPathComponent("engine/main.py").path ?? ""
        let repoMain = "/Users/rodrigocruzsouza/fluent/fluent-engine/main.py"
        let mainPy = FileManager.default.fileExists(atPath: bundledMain) ? bundledMain : repoMain

        guard FileManager.default.fileExists(atPath: mainPy) else {
            print("[Fluent] engine main.py not found")
            return
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = [mainPy]
        // Inherit the Swift app's TCC permissions (including microphone)
        process.currentDirectoryURL = URL(fileURLWithPath: mainPy).deletingLastPathComponent()
        let logURL = URL(fileURLWithPath: "/tmp/fluent-engine.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        if let fh = try? FileHandle(forWritingTo: logURL) {
            fh.seekToEndOfFile()
            process.standardOutput = fh
            process.standardError = fh
        }
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                self?.startEngine() // auto-restart on crash
            }
        }
        do {
            try process.run()
            engineProcess = process
            print("[Fluent] engine started (pid \(process.processIdentifier))")
        } catch {
            print("[Fluent] failed to start engine: \(error)")
        }
    }

    // MARK: - Menu

    private func setupMenu() {
        let mainMenu = NSMenu()
        let appMenuItem = NSMenuItem()
        mainMenu.addItem(appMenuItem)
        let appMenu = NSMenu()
        appMenuItem.submenu = appMenu
        appMenu.addItem(NSMenuItem(title: "Settings", action: #selector(openSettings), keyEquivalent: ","))
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(NSMenuItem(title: "Sign Out", action: #selector(signOut), keyEquivalent: ""))
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(NSMenuItem(title: "Quit Fluent", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        NSApp.mainMenu = mainMenu
    }

    @objc private func openSettings() {
        showReport()
        reportWindowController?.showSettings()
    }

    @objc private func signOut() {
        // Always clear the JS token and show onboarding regardless of engine state
        var req = URLRequest(url: URL(string: "http://127.0.0.1:2788/signout")!)
        req.httpMethod = "POST"
        URLSession.shared.dataTask(with: req) { _, _, _ in }.resume()
        reportWindowController?.clearTokenAndShowOnboarding()
    }

    private func showOnboarding() {
        showReport()
        reportWindowController?.showOnboarding()
    }

    func applicationWillTerminate(_ notification: Notification) {
        engineProcess?.terminate()
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

    // MARK: - UNUserNotificationCenterDelegate

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler handler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        handler([.banner, .sound])
    }
}
