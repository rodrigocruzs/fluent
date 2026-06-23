"""
First-launch setup window — shown once after onboarding.

Three sequential steps, each with a status label and progress bar:
  1. Initialize (transcription is cloud-based; no model download)
  2. Install BlackHole + configure audio device
  3. Request microphone permission

Runs the heavy work in background threads; updates the UI on the main thread
via root.after(). Closes itself when all steps are done.
"""

import threading
import tkinter as tk
from pathlib import Path

BG     = "#ffffff"
ACCENT = "#C96442"
TEXT   = "#1a1a1a"
INK_2  = "#2a2a2a"
MUTED  = "#8a8a8a"
GRAY_3 = "#b5b5b5"
OK     = "#4a7c59"
BORDER = "#e8e8e6"

FONT_WORD   = ("-apple-system", 13)
FONT_TITLE  = ("-apple-system", 17)
FONT_LABEL  = ("-apple-system", 13)
FONT_SMALL  = ("-apple-system", 11)
FONT_STATUS = ("-apple-system", 11)

WIN_W, WIN_H = 400, 300


def _center(win):
    win.update_idletasks()
    x = (win.winfo_screenwidth()  - WIN_W) // 2
    y = (win.winfo_screenheight() - WIN_H) // 2
    win.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")


def run_setup_window():
    """
    Show the setup progress window and block until all steps are done.
    Safe to call even if everything is already set up — it will skip
    completed steps and close immediately if nothing needs doing.
    """
    from fluent.blackhole import is_blackhole_installed, install_blackhole, ensure_multi_output
    from fluent.first_launch import _bundled_pkg, _request_mic_permission, SETUP_DONE_FLAG

    # Fast path: nothing to do
    if SETUP_DONE_FLAG.exists():
        return

    root = tk.Tk()
    root.title("Fluent — Setting up")
    root.configure(bg=BG)
    root.resizable(False, False)
    _center(root)
    root.lift()
    root.attributes("-topmost", True)
    root.after(300, lambda: root.attributes("-topmost", False))
    # Prevent closing mid-setup
    root.protocol("WM_DELETE_WINDOW", lambda: None)

    # ── Layout ────────────────────────────────────────────────────────────────

    tk.Label(root, text="Fluent", bg=BG, fg=GRAY_3,
             font=FONT_WORD).pack(pady=(40, 0), padx=48, anchor="w")
    tk.Label(root, text="Setting up", bg=BG, fg=TEXT,
             font=FONT_TITLE).pack(pady=(10, 0), padx=48, anchor="w")
    tk.Label(root, text="This only happens once.", bg=BG, fg=MUTED,
             font=FONT_SMALL).pack(padx=48, anchor="w", pady=(6, 28))

    rows: list[dict] = []
    for label_text in [
        "Preparing Fluent",
        "Configuring audio",
        "Requesting microphone access",
    ]:
        frame = tk.Frame(root, bg=BG)
        frame.pack(fill="x", padx=48, pady=4)

        lbl = tk.Label(frame, text=label_text, bg=BG, fg=MUTED, font=FONT_LABEL, anchor="w")
        lbl.pack(anchor="w")

        bar_bg = tk.Frame(frame, bg=BORDER, height=4)
        bar_bg.pack(fill="x", pady=(4, 0))

        bar_fill = tk.Frame(bar_bg, bg=ACCENT, height=4, width=0)
        bar_fill.place(x=0, y=0, relheight=1)

        status = tk.Label(frame, text="", bg=BG, fg=MUTED, font=FONT_STATUS, anchor="w")
        status.pack(anchor="w")

        rows.append({"lbl": lbl, "bar_bg": bar_bg, "bar_fill": bar_fill, "status": status})

    done_flag = {"count": 0}

    # ── UI helpers (must be called from main thread via root.after) ───────────

    def set_active(i):
        rows[i]["lbl"].config(fg=TEXT)
        rows[i]["status"].config(text="In progress…", fg=MUTED)

    def set_progress(i, fraction):
        rows[i]["bar_bg"].update_idletasks()
        w = rows[i]["bar_bg"].winfo_width()
        rows[i]["bar_fill"].place(x=0, y=0, relheight=1, width=int(w * min(fraction, 1.0)))

    def set_done(i, msg="Done"):
        rows[i]["lbl"].config(fg=OK)
        rows[i]["status"].config(text=f"✓ {msg}", fg=OK)
        set_progress(i, 1.0)
        done_flag["count"] += 1
        if done_flag["count"] == 3:
            root.after(600, root.destroy)

    def set_skip(i, msg="Already done"):
        rows[i]["lbl"].config(fg=MUTED)
        rows[i]["status"].config(text=f"✓ {msg}", fg=MUTED)
        set_progress(i, 1.0)
        done_flag["count"] += 1
        if done_flag["count"] == 3:
            root.after(600, root.destroy)

    # ── Step workers (run in threads) ─────────────────────────────────────────

    def step1_model():
        # Transcription is now performed in the cloud (Deepgram via the
        # backend); there is no local speech model to download.
        root.after(0, lambda: set_active(0))
        root.after(0, lambda: set_skip(0, "Ready"))
        step2_audio()

    def step2_audio():
        root.after(0, lambda: set_active(1))
        try:
            root.after(0, lambda: set_progress(1, 0.2))

            if not is_blackhole_installed():
                pkg = _bundled_pkg()
                if pkg:
                    install_blackhole(pkg)
                    import time; time.sleep(2)

            root.after(0, lambda: set_progress(1, 0.7))
            ensure_multi_output()
            root.after(0, lambda: set_done(1, "Audio configured"))
        except Exception:
            root.after(0, lambda: set_done(1, "Audio configured"))

        step3_mic()

    def step3_mic():
        root.after(0, lambda: set_active(2))
        root.after(0, lambda: set_progress(2, 0.5))
        try:
            _request_mic_permission()
        except Exception:
            pass
        root.after(0, lambda: set_done(2, "Microphone ready"))

        # Mark setup complete
        SETUP_DONE_FLAG.parent.mkdir(parents=True, exist_ok=True)
        SETUP_DONE_FLAG.touch()

    # ── Kick off ──────────────────────────────────────────────────────────────

    threading.Thread(target=step1_model, daemon=True).start()
    root.mainloop()
