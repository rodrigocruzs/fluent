import Cocoa
import UserNotifications
import AVFoundation
import Sparkle

class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate, @unchecked Sendable {

    private var reportWindowController: ReportWindowController?
    private var engineSetupProcess: Process?
    private var engineProcess: Process?
    private var setupWindowController: EngineSetupWindowController?
    private var updaterController: SPUStandardUpdaterController!

    // Crash-loop guard: if the engine keeps dying immediately we back off and
    // eventually stop auto-restarting instead of spinning the CPU forever.
    private var engineRestartCount = 0
    private var lastEngineStart = Date.distantPast
    private static let maxEngineRestarts = 5

    /// Setup is "done" only when the script wrote this sentinel after a fully
    /// validated install — NOT merely when a venv python exists (a half-finished
    /// install leaves the venv but no sentinel, so we correctly retry).
    private var engineReadySentinel: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".fluent/engine/.engine-ready")
    }

    // Exit codes from setup_engine.sh — kept in sync with the script.
    private enum EngineSetupError: Int32 {
        case noPython = 10
        case venvFailed = 11
        case pipFailed = 12
        case verifyFailed = 13
    }

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
        // Already fully set up and validated → just start.
        if FileManager.default.fileExists(atPath: engineReadySentinel.path) {
            startEngine()
            return
        }
        runEngineSetup()
    }

    /// Runs the first-launch (or retry) engine setup, surfacing progress and
    /// actionable errors to the user instead of failing silently.
    private func runEngineSetup() {
        // Bail early with clear guidance if there's no usable Python at all —
        // no point spawning the script just to have it exit 10.
        guard findSystemPython() != nil else {
            DispatchQueue.main.async { [weak self] in self?.showPythonMissing() }
            return
        }

        guard
            let engineSrc = Bundle.main.resourceURL?.appendingPathComponent("fluent-engine"),
            let setupScript = Bundle.main.path(forResource: "setup_engine", ofType: "sh", inDirectory: "fluent-engine")
        else {
            print("[Fluent] setup_engine.sh not found in bundle — skipping engine setup")
            return
        }

        print("[Fluent] Running engine setup...")
        DispatchQueue.main.async { [weak self] in self?.showSetupProgress() }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [setupScript, engineSrc.path]
        process.terminationHandler = { [weak self] p in
            let status = p.terminationStatus
            DispatchQueue.main.async {
                guard let self else { return }
                if status == 0 {
                    print("[Fluent] Engine setup complete.")
                    self.dismissSetupWindow()
                    self.engineRestartCount = 0
                    self.startEngine()
                } else {
                    print("[Fluent] Engine setup failed (status \(status)). See ~/.fluent/engine-setup.log")
                    self.showSetupFailed(EngineSetupError(rawValue: status))
                }
            }
        }
        do {
            try process.run()
            engineSetupProcess = process
        } catch {
            print("[Fluent] failed to launch setup: \(error)")
            DispatchQueue.main.async { [weak self] in self?.showSetupFailed(nil) }
        }
    }

    /// Mirror of setup_engine.sh's find_python: returns a usable Python 3.10+,
    /// checking well-known absolute paths first (the inherited PATH may only have
    /// the macOS system Python 3.9).
    private func findSystemPython() -> String? {
        let candidates = [
            "/opt/homebrew/bin/python3.13", "/opt/homebrew/bin/python3.12",
            "/opt/homebrew/bin/python3.11", "/opt/homebrew/bin/python3.10",
            "/usr/local/bin/python3.13", "/usr/local/bin/python3.12",
            "/usr/local/bin/python3.11", "/usr/local/bin/python3.10",
            "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
            "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3",
            "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3",
            "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3",
        ]
        for path in candidates where isPython310Plus(path) {
            return path
        }
        return nil
    }

    private func isPython310Plus(_ path: String) -> Bool {
        guard FileManager.default.isExecutableFile(atPath: path) else { return false }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: path)
        p.arguments = ["-c", "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)"]
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do {
            try p.run()
            p.waitUntilExit()
            return p.terminationStatus == 0
        } catch {
            return false
        }
    }

    // MARK: - Setup UI

    private func showSetupProgress() {
        if setupWindowController == nil {
            setupWindowController = EngineSetupWindowController()
        }
        setupWindowController?.showProgress()
    }

    private func dismissSetupWindow() {
        setupWindowController?.close()
        setupWindowController = nil
    }

    private func showPythonMissing() {
        let alert = NSAlert()
        alert.messageText = "Python is required"
        alert.informativeText = """
        Fluent needs Python 3.10 or newer to process your recordings. \
        It doesn't look like a compatible version is installed.

        Install Python from python.org, then click Retry.
        """
        alert.addButton(withTitle: "Open python.org")
        alert.addButton(withTitle: "Retry")
        alert.addButton(withTitle: "Later")
        switch alert.runModal() {
        case .alertFirstButtonReturn:
            NSWorkspace.shared.open(URL(string: "https://www.python.org/downloads/macos/")!)
        case .alertSecondButtonReturn:
            runEngineSetup()
        default:
            break
        }
    }

    private func showSetupFailed(_ reason: EngineSetupError?) {
        dismissSetupWindow()
        let alert = NSAlert()
        alert.messageText = "Couldn't finish setup"
        switch reason {
        case .noPython:
            showPythonMissing()
            return
        case .pipFailed:
            alert.informativeText = "Downloading Fluent's processing components failed. "
                + "Check your internet connection and try again."
        case .verifyFailed, .venvFailed, .none:
            alert.informativeText = "Something went wrong while setting up the engine. "
                + "You can retry, or see ~/.fluent/engine-setup.log for details."
        }
        alert.addButton(withTitle: "Retry")
        alert.addButton(withTitle: "Later")
        if alert.runModal() == .alertFirstButtonReturn {
            runEngineSetup()
        }
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

        // Only the venv python has the installed deps. If it's missing the install
        // is incomplete — re-run setup rather than launching a Python that will
        // crash on `import torch` and trigger an endless restart loop.
        let venvPython = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".fluent/engine/venv/bin/python3").path
        guard FileManager.default.isExecutableFile(atPath: venvPython) else {
            print("[Fluent] venv python missing — (re)running setup")
            runEngineSetup()
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
        process.executableURL = URL(fileURLWithPath: venvPython)
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
