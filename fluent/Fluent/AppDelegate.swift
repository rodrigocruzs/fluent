import Cocoa
import UserNotifications
import AVFoundation
import Sparkle

class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate, @unchecked Sendable {

    private var reportWindowController: ReportWindowController?
    private var engineProcess: Process?
    private var updaterController: SPUStandardUpdaterController!

    // Crash-loop guard: if the engine keeps dying immediately we back off and
    // eventually stop auto-restarting instead of spinning the CPU forever.
    private var engineRestartCount = 0
    private var lastEngineStart = Date.distantPast
    private static let maxEngineRestarts = 5

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        setupMenu()

        updaterController = SPUStandardUpdaterController(
            startingUpdater: true,
            updaterDelegate: nil,
            userDriverDelegate: nil
        )

        UNUserNotificationCenter.current().delegate = self
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }

        DarwinNotificationBridge.shared.startListening(name: "com.fluent.reportReady") { [weak self] in
            DispatchQueue.main.async { self?.showLatestReport() }
        }

        requestMicrophonePermission()
        migrateLegacyEngineIfNeeded()
        installEngineLaunchAgentIfNeeded()
        startEngine()
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

    // MARK: - Engine runtime

    private static let engineAgentLabel = "com.fluent.engine"

    private var engineAgentPlistURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/\(Self.engineAgentLabel).plist")
    }

    private var bundledEnginePython: String? {
        guard let path = Bundle.main.resourceURL?
            .appendingPathComponent("engine-runtime/bin/python3").path,
            FileManager.default.isExecutableFile(atPath: path) else { return nil }
        return path
    }

    /// Interpreter resolution: dev override → bundled runtime (release builds)
    /// → legacy venv (Debug builds on dev machines, where the bundled runtime
    /// isn't in the Xcode-built bundle).
    private func enginePython() -> String? {
        if let override = ProcessInfo.processInfo.environment["FLUENT_ENGINE_PYTHON"],
           FileManager.default.isExecutableFile(atPath: override) {
            print("[Fluent] using FLUENT_ENGINE_PYTHON override: \(override)")
            return override
        }
        if let bundled = bundledEnginePython { return bundled }
        let legacy = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".fluent/engine/venv/bin/python3").path
        if FileManager.default.isExecutableFile(atPath: legacy) {
            print("[Fluent] bundled runtime missing — using legacy venv python (dev build)")
            return legacy
        }
        return nil
    }

    /// One-time cleanup of the pre-bundled-runtime install (venv + rsync'd
    /// engine + sentinel). Only runs when this build actually carries the
    /// bundled runtime — Debug builds still rely on the venv.
    /// Never touches user data (~/.fluent/config.json, reports/, recordings/).
    private func migrateLegacyEngineIfNeeded() {
        guard bundledEnginePython != nil else { return }
        let legacyDir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".fluent/engine")
        guard FileManager.default.fileExists(atPath: legacyDir.path) else { return }
        runLaunchctl(["bootout", "gui/\(getuid())/\(Self.engineAgentLabel)"])
        try? FileManager.default.removeItem(at: legacyDir)
        print("[Fluent] migrated: removed legacy engine install at ~/.fluent/engine")
    }

    /// The agent runs the bundled runtime against the bundled engine source —
    /// release builds only (Debug builds return nil and leave any agent as-is).
    private func desiredEngineAgentPlistData() -> Data? {
        guard let resources = Bundle.main.resourceURL else { return nil }
        let python = resources.appendingPathComponent("engine-runtime/bin/python3")
        let mainPy = resources.appendingPathComponent("fluent-engine/main.py")
        guard FileManager.default.isExecutableFile(atPath: python.path),
              FileManager.default.fileExists(atPath: mainPy.path) else { return nil }
        let plist: [String: Any] = [
            "Label": Self.engineAgentLabel,
            "ProgramArguments": [python.path, mainPy.path],
            "RunAtLoad": true,
            "KeepAlive": true,
            "StandardOutPath": "/tmp/fluent-engine.log",
            "StandardErrorPath": "/tmp/fluent-engine.log",
            "WorkingDirectory": mainPy.deletingLastPathComponent().path,
            "EnvironmentVariables": [
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            ],
        ]
        return try? PropertyListSerialization.data(
            fromPropertyList: plist, format: .xml, options: 0)
    }

    /// Installs/refreshes the Launch Agent so it always points at the current
    /// bundle location (self-heals across app moves and Sparkle updates).
    private func installEngineLaunchAgentIfNeeded() {
        guard let desired = desiredEngineAgentPlistData() else { return }
        if let existing = try? Data(contentsOf: engineAgentPlistURL), existing == desired {
            return
        }
        let dir = engineAgentPlistURL.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        do {
            try desired.write(to: engineAgentPlistURL)
        } catch {
            print("[Fluent] failed to write launch agent plist: \(error)")
            return
        }
        runLaunchctl(["bootout", "gui/\(getuid())/\(Self.engineAgentLabel)"])
        runLaunchctl(["bootstrap", "gui/\(getuid())", engineAgentPlistURL.path])
        print("[Fluent] launch agent installed: \(engineAgentPlistURL.path)")
    }

    @discardableResult
    private func runLaunchctl(_ args: [String]) -> Int32 {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        p.arguments = args
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return -1 }
        p.waitUntilExit()
        return p.terminationStatus
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

        guard let python = enginePython() else {
            print("[Fluent] no engine interpreter available — engine not started")
            return
        }

        // Find main.py inside the app bundle
        guard let mainPy = Bundle.main.resourceURL?
            .appendingPathComponent("fluent-engine/main.py").path,
              FileManager.default.fileExists(atPath: mainPy) else {
            print("[Fluent] engine main.py not found in bundle")
            return
        }

        lastEngineStart = Date()
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = [mainPy]
        // Inherit the Swift app's TCC permissions (including microphone)
        process.currentDirectoryURL = URL(fileURLWithPath: mainPy).deletingLastPathComponent()
        var env = ProcessInfo.processInfo.environment
        env["PYTHONNOUSERSITE"] = "1"        // don't leak ~/.local site-packages
        env["PYTHONDONTWRITEBYTECODE"] = "1" // bundle is read-only + codesigned
        process.environment = env
        let logURL = URL(fileURLWithPath: "/tmp/fluent-engine.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        if let fh = try? FileHandle(forWritingTo: logURL) {
            fh.seekToEndOfFile()
            process.standardOutput = fh
            process.standardError = fh
        }
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async { self?.handleEngineExit() }
        }
        do {
            try process.run()
            engineProcess = process
            print("[Fluent] engine started (pid \(process.processIdentifier))")
        } catch {
            print("[Fluent] failed to start engine: \(error)")
        }
    }

    /// Auto-restart the engine on crash, but with back-off and a cap so a
    /// reliably-crashing engine can't spin the CPU in a tight loop forever.
    private func handleEngineExit() {
        // A process that survived a while is a normal crash, not a startup loop —
        // reset the counter so transient crashes don't count toward the cap.
        if Date().timeIntervalSince(lastEngineStart) > 30 {
            engineRestartCount = 0
        }

        engineRestartCount += 1
        guard engineRestartCount <= Self.maxEngineRestarts else {
            print("[Fluent] engine crashed \(engineRestartCount) times — giving up auto-restart")
            return
        }

        // Linear back-off: 2s, 4s, 6s, …
        let delay = Double(engineRestartCount) * 2.0
        print("[Fluent] engine exited — restarting in \(delay)s (attempt \(engineRestartCount))")
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            self?.startEngine()
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
