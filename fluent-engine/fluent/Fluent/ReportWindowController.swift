import Cocoa

class ReportWindowController: NSWindowController {

    convenience init() {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1080, height: 720),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = "Fluent"
        window.titlebarAppearsTransparent = false
        window.minSize = NSSize(width: 640, height: 480)
        window.center()
        window.setFrameAutosaveName("FluentReportWindow")

        let vc = WebViewController()
        window.contentViewController = vc
        self.init(window: window)
    }

    private var webViewController: WebViewController? {
        window?.contentViewController as? WebViewController
    }

    /// Pass a raw JSON string — avoids [String: Any] Sendable issues.
    func loadReportJSON(_ json: String) {
        webViewController?.loadReportJSON(json)
    }
}
