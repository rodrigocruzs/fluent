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
            let engineSrc = Bundle.main.resourceURL?.appendingPathComponent("fluent-engine"),
            let setupScript = Bundle.main.path(forResource: "setup_engine", ofType: "sh", inDirectory: "fluent-engine")
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

    /// Terminate whatever process is listening on the given TCP port (best effort).
    private func killProcessOnPort(_ port: Int) {
        let lsof = Process()
        lsof.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        lsof.arguments = ["-nP", "-tiTCP:\(port)", "-sTCP:LISTEN"]
        let pipe = Pipe()
        lsof.standardOutput = pipe
        lsof.standardError = FileHandle.nullDevice
        do {
            try lsof.run()
            lsof.waitUntilExit()
        } catch {
            return
        }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        guard let out = String(data: data, encoding: .utf8) else { return }
        for line in out.split(whereSeparator: { $0 == "\n" || $0 == " " }) {
            guard let pid = Int32(line.trimmingCharacters(in: .whitespaces)),
                  pid != ProcessInfo.processInfo.processIdentifier else { continue }
            kill(pid, SIGTERM)
            print("[Fluent] terminated stale engine on port \(port) (pid \(pid))")
        }
    }

    private func startEngine() {
        // Kill any existing engine process
        engineProcess?.terminate()
        engineProcess = nil

        // Kill any orphaned engine from a previous session that still owns port 2788.
        // Otherwise the freshly launched engine can't bind the port, and all requests
        // keep hitting the stale process (which may be running outdated code).
        killProcessOnPort(2788)

        // Prefer the venv python (set up by setup_engine.sh), fall back to system Python
        let venvPython = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".fluent/engine/venv/bin/python3").path
        let systemPython = "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
        let pythonPath = FileManager.default.fileExists(atPath: venvPython) ? venvPython : systemPython

        // Find main.py inside the app bundle
        guard let mainPy = Bundle.main.resourceURL?
            .appendingPathComponent("fluent-engine/main.py").path,
              FileManager.default.fileExists(atPath: mainPy) else {
            print("[Fluent] engine main.py not found in bundle")
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

    func applicationDidBecomeActive(_ notification: Notification) {
        reportWindowController?.syncBillingStatus()
    }

    func applicationWillTerminate(_ notification: Notification) {
        engineProcess?.terminate()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if !hasVisibleWindows { showReport() }
        return true
    }

    // MARK: - URL scheme handler (fluent://auth?token=...&name=...&email=...)

    func application(_ application: NSApplication, open urls: [URL]) {
        guard let url = urls.first,
              url.scheme == "fluent",
              url.host == "auth" else { return }

        let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        let params = Dictionary(
            uniqueKeysWithValues: (components?.queryItems ?? []).compactMap { item -> (String, String)? in
                guard let value = item.value else { return nil }
                return (item.name, value)
            }
        )

        if let errorMsg = params["error"] {
            showReport()
            reportWindowController?.showGoogleAuthError(errorMsg)
            return
        }

        guard let token = params["token"] else { return }
        let name  = params["name"]  ?? ""
        let email = params["email"] ?? ""

        showReport()
        reportWindowController?.handleGoogleAuthCallback(token: token, name: name, email: email)
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
        // A new report means a new session was just saved to the backend.
        // Refresh the History list natively (the webview can't fetch it itself
        // due to CORS) so the session appears when the user navigates back.
        reportWindowController?.refreshSessions()
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
