import Cocoa
import WebKit

class WebViewController: NSViewController, WKScriptMessageHandler {

    private var webView: WKWebView!
    private var pendingReportJSON: String?

    private let reportsDir: URL = {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".fluent/reports")
    }()

    override func loadView() {
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        // Allow JS on the page to call back into Swift to open a specific session
        config.userContentController.add(self, name: "openSession")

        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        view = webView
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        loadHTML()
    }

    // MARK: - HTML loading

    private func loadHTML() {
        if let url = Bundle.main.url(
            forResource: "report",
            withExtension: "html",
            subdirectory: "frontend"
        ) {
            print("[Fluent] loading from bundle: \(url.path)")
            webView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
            return
        }

        // In dev, the executable lives at: .../fluent/fluent/build/Build/Products/Debug/Fluent.app/Contents/MacOS/Fluent
        // Walk up to repo root: MacOS/ → Contents/ → Fluent.app/ → Debug/ → Products/ → Build/ → build/ → fluent/ → repo root
        // Exe: .../fluent/fluent/build/Build/Products/Debug/Fluent.app/Contents/MacOS/Fluent
        let exe = URL(fileURLWithPath: CommandLine.arguments[0]).standardized
        let repoRoot = exe
            .deletingLastPathComponent()  // MacOS/
            .deletingLastPathComponent()  // Contents/
            .deletingLastPathComponent()  // Fluent.app/
            .deletingLastPathComponent()  // Debug/
            .deletingLastPathComponent()  // Products/
            .deletingLastPathComponent()  // Build/
            .deletingLastPathComponent()  // build/
            .deletingLastPathComponent()  // fluent/ (inner Xcode project dir)
            .deletingLastPathComponent()  // fluent/ (repo root)
        let devURL = repoRoot.appendingPathComponent("frontend/report.html")

        print("[Fluent] trying dev path: \(devURL.path)")
        print("[Fluent] trying dev path: \(devURL.path)")
        if FileManager.default.fileExists(atPath: devURL.path) {
            webView.loadFileURL(devURL, allowingReadAccessTo: devURL.deletingLastPathComponent())
        } else {
            print("[Fluent] report.html not found — loading inline fallback")
            webView.loadHTMLString("<html><body style='font-family:system-ui;padding:40px'><h1>Fluent</h1><p style=\"color:#888\">frontend/report.html not found at: \(devURL.path)</p></body></html>", baseURL: nil)
        }
    }

    // MARK: - Sessions list (shown on startup)

    private func injectSessions() {
        let sessionsURL = reportsDir.appendingPathComponent("sessions.json")
        guard
            let data = try? Data(contentsOf: sessionsURL),
            let json = String(data: data, encoding: .utf8)
        else {
            // No sessions yet — show onboarding
            return
        }
        let js = "window.loadSessions(\(json));"
        webView.evaluateJavaScript(js) { _, error in
            if let error { print("[Fluent WebView] loadSessions error:", error) }
        }
    }

    // MARK: - Report injection (latest or specific)

    func loadReportJSON(_ json: String) {
        guard !webView.isLoading, webView.url != nil else {
            pendingReportJSON = json
            return
        }
        injectReport(json: json)
    }

    private func injectReport(json: String) {
        let js = "window.loadReport(\(json));"
        webView.evaluateJavaScript(js) { _, error in
            if let error { print("[Fluent WebView] loadReport error:", error) }
        }
    }

    // MARK: - WKScriptMessageHandler (JS → Swift: open a specific session)

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "openSession", let slug = message.body as? String else { return }
        let sessionURL = reportsDir.appendingPathComponent("\(slug).json")
        guard
            let data = try? Data(contentsOf: sessionURL),
            let json = String(data: data, encoding: .utf8)
        else {
            print("[Fluent] session JSON not found for slug: \(slug)")
            return
        }
        injectReport(json: json)
    }
}

// MARK: - WKNavigationDelegate
extension WebViewController: WKNavigationDelegate {
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        print("[Fluent] webView didFinish: \(webView.url?.absoluteString ?? "nil")")
        if let json = pendingReportJSON {
            pendingReportJSON = nil
            injectReport(json: json)
        } else {
            injectSessions()
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        print("[Fluent] webView didFail: \(error)")
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        print("[Fluent] webView didFailProvisional: \(error)")
    }
}
