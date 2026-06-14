import Cocoa

/// A small, borderless progress window shown during first-launch engine setup,
/// while `setup_engine.sh` downloads and installs the Python processing
/// dependencies (which can take several minutes). Without it the app looks
/// frozen on first run.
class EngineSetupWindowController: NSWindowController {

    private let spinner = NSProgressIndicator()

    init() {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 420, height: 180),
            styleMask: [.titled, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = "Setting up Fluent"
        window.titlebarAppearsTransparent = true
        window.isMovableByWindowBackground = true
        super.init(window: window)
        window.center()
        buildContent()
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    private func buildContent() {
        guard let content = window?.contentView else { return }

        let title = NSTextField(labelWithString: "Getting Fluent ready")
        title.font = .systemFont(ofSize: 16, weight: .semibold)
        title.alignment = .center
        title.translatesAutoresizingMaskIntoConstraints = false

        let subtitle = NSTextField(wrappingLabelWithString:
            "Downloading the components Fluent uses to transcribe your meetings. "
            + "This happens once and may take a few minutes.")
        subtitle.font = .systemFont(ofSize: 12)
        subtitle.textColor = .secondaryLabelColor
        subtitle.alignment = .center
        subtitle.translatesAutoresizingMaskIntoConstraints = false

        spinner.style = .spinning
        spinner.controlSize = .regular
        spinner.translatesAutoresizingMaskIntoConstraints = false
        spinner.startAnimation(nil)

        content.addSubview(title)
        content.addSubview(subtitle)
        content.addSubview(spinner)

        NSLayoutConstraint.activate([
            title.topAnchor.constraint(equalTo: content.topAnchor, constant: 36),
            title.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 24),
            title.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -24),

            subtitle.topAnchor.constraint(equalTo: title.bottomAnchor, constant: 8),
            subtitle.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 24),
            subtitle.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -24),

            spinner.topAnchor.constraint(equalTo: subtitle.bottomAnchor, constant: 20),
            spinner.centerXAnchor.constraint(equalTo: content.centerXAnchor),
        ])
    }

    /// Show (or re-show) the progress window and bring it to front.
    func showProgress() {
        spinner.startAnimation(nil)
        showWindow(nil)
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}
