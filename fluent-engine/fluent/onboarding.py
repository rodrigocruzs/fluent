"""
Two-screen onboarding UI. Design matches the coaching report:
system font, white background, single #C96442 accent, typographic.

Screen 1: email + password — Create account / Log in
Screen 2: native language + role
"""

import tkinter as tk
import httpx

from fluent.coach import register, login, save_token, get_token
from fluent.config import Config

# ── Design tokens (match report CSS) ────────────────────────────────────────
BG        = "#ffffff"
INK       = "#1a1a1a"
INK_2     = "#2a2a2a"
GRAY_1    = "#555555"
GRAY_2    = "#8a8a8a"
GRAY_3    = "#b5b5b5"
RULE      = "#e8e8e6"
ACCENT    = "#C96442"
ACCENT_HV = "#a8512f"
ERROR     = "#cc3333"

FONT_WORD  = ("-apple-system", 13)
FONT_TITLE = ("-apple-system", 22)
FONT_LABEL = ("-apple-system", 13)
FONT_SMALL = ("-apple-system", 11)
FONT_BTN   = ("-apple-system", 14)
FONT_MUTED = ("-apple-system", 11)

WIN_W, WIN_H = 440, 500


def _center(win):
    win.update_idletasks()
    x = (win.winfo_screenwidth()  - WIN_W) // 2
    y = (win.winfo_screenheight() - WIN_H) // 2
    win.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")


def _rule(parent):
    tk.Frame(parent, bg=RULE, height=1).pack(fill="x", pady=(0, 0))


def _entry(parent, show=None) -> tk.Entry:
    e = tk.Entry(
        parent,
        font=FONT_LABEL,
        bg=BG, fg=INK, insertbackground=INK,
        relief="flat", bd=0,
        highlightthickness=1,
        highlightbackground=RULE,
        highlightcolor=ACCENT,
    )
    if show:
        e.config(show=show)
    return e


def _primary_btn(parent, text, command) -> tk.Button:
    """Native tk.Button with system chrome stripped — reliable on macOS."""
    b = tk.Button(
        parent, text=text, command=command,
        font=FONT_BTN, fg="white",
        activeforeground="white",
        relief="flat", bd=0,
        highlightthickness=0,
        padx=0, pady=11,
        cursor="hand2",
    )
    # bg must be set after creation to survive macOS theme override
    b.config(bg=ACCENT, activebackground=ACCENT_HV)
    return b


def _link(parent, text, command) -> tk.Label:
    lbl = tk.Label(parent, text=text, bg=BG, fg=GRAY_2,
                   font=FONT_MUTED, cursor="hand2")
    lbl.bind("<Button-1>", lambda e: command())
    lbl.bind("<Enter>", lambda e: lbl.config(fg=ACCENT))
    lbl.bind("<Leave>", lambda e: lbl.config(fg=GRAY_2))
    return lbl


# ── Screen 1: Auth ────────────────────────────────────────────────────────────

class AuthScreen(tk.Frame):
    def __init__(self, master, on_success):
        super().__init__(master, bg=BG)
        self._on_success = on_success
        self._build()

    def _build(self):
        p = dict(padx=48)

        # Wordmark
        tk.Label(self, text="Fluent", bg=BG, fg=GRAY_3,
                 font=FONT_WORD).pack(anchor="w", pady=(48, 0), **p)

        # Title
        tk.Label(self, text="Create your account", bg=BG, fg=INK,
                 font=FONT_TITLE).pack(anchor="w", pady=(12, 0), **p)
        tk.Label(self, text="Your personal English coach, no setup required.",
                 bg=BG, fg=GRAY_2, font=FONT_SMALL).pack(anchor="w", pady=(6, 36), **p)

        # Email
        tk.Label(self, text="Email", bg=BG, fg=GRAY_1,
                 font=FONT_LABEL).pack(anchor="w", **p)
        self._email = _entry(self)
        self._email.pack(fill="x", ipady=9, pady=(6, 20), **p)

        # Password
        tk.Label(self, text="Password", bg=BG, fg=GRAY_1,
                 font=FONT_LABEL).pack(anchor="w", **p)
        self._pw = _entry(self, show="•")
        self._pw.pack(fill="x", ipady=9, pady=(6, 6), **p)
        tk.Label(self, text="At least 8 characters", bg=BG, fg=GRAY_3,
                 font=FONT_SMALL).pack(anchor="w", pady=(0, 28), **p)

        # Error
        self._err = tk.Label(self, text="", bg=BG, fg=ERROR,
                             font=FONT_SMALL, wraplength=344, justify="left")
        self._err.pack(anchor="w", pady=(0, 10), **p)

        # Button
        _primary_btn(self, "Create account", self._do_register).pack(
            fill="x", ipady=0, **p)

        # Log in link
        row = tk.Frame(self, bg=BG)
        row.pack(pady=14)
        tk.Label(row, text="Already have an account?", bg=BG, fg=GRAY_3,
                 font=FONT_MUTED).pack(side="left")
        _link(row, "  Log in", self._do_login).pack(side="left")

        self._email.focus_set()
        self.master.bind("<Return>", lambda e: self._do_register())

    def _credentials(self):
        email = self._email.get().strip()
        pw    = self._pw.get()
        if not email or "@" not in email:
            self._err.config(text="Please enter a valid email address.")
            return None, None
        if len(pw) < 8:
            self._err.config(text="Password must be at least 8 characters.")
            return None, None
        self._err.config(text="")
        return email, pw

    def _do_register(self):
        email, pw = self._credentials()
        if not email:
            return
        self._err.config(text="")
        try:
            save_token(register(email, pw))
            self._on_success()
        except httpx.HTTPStatusError as e:
            self._err.config(text=e.response.json().get("detail", str(e)))
        except Exception as e:
            self._err.config(text=f"Could not connect to server. {e}")

    def _do_login(self):
        email, pw = self._credentials()
        if not email:
            return
        self._err.config(text="")
        try:
            save_token(login(email, pw))
            self._on_success()
        except httpx.HTTPStatusError as e:
            self._err.config(text=e.response.json().get("detail", str(e)))
        except Exception as e:
            self._err.config(text=f"Could not connect to server. {e}")


# ── Screen 2: Setup ───────────────────────────────────────────────────────────

class SetupScreen(tk.Frame):
    def __init__(self, master, on_success):
        super().__init__(master, bg=BG)
        self._on_success = on_success
        self._build()

    def _build(self):
        p = dict(padx=48)

        tk.Label(self, text="Fluent", bg=BG, fg=GRAY_3,
                 font=FONT_WORD).pack(anchor="w", pady=(48, 0), **p)
        tk.Label(self, text="One quick thing", bg=BG, fg=INK,
                 font=FONT_TITLE).pack(anchor="w", pady=(12, 0), **p)
        tk.Label(
            self,
            text="Fluent tailors feedback to your background.",
            bg=BG, fg=GRAY_2, font=FONT_SMALL, justify="left",
        ).pack(anchor="w", pady=(6, 36), **p)

        tk.Label(self, text="Your native language", bg=BG, fg=GRAY_1,
                 font=FONT_LABEL).pack(anchor="w", **p)
        self._lang = _entry(self)
        self._lang.insert(0, "Spanish")
        self._lang.pack(fill="x", ipady=9, pady=(6, 20), **p)

        tk.Label(self, text="Your role", bg=BG, fg=GRAY_1,
                 font=FONT_LABEL).pack(anchor="w", **p)
        self._role = _entry(self)
        self._role.insert(0, "Product Manager")
        self._role.pack(fill="x", ipady=9, pady=(6, 36), **p)

        _primary_btn(self, "Let's go", self._save).pack(fill="x", **p)

        self._lang.focus_set()
        self.master.bind("<Return>", lambda e: self._save())

    def _save(self):
        lang = self._lang.get().strip() or "Spanish"
        role = self._role.get().strip() or "Professional"
        Config(native_language=lang, job_context=role).save()
        self._on_success()


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run_onboarding() -> bool:
    result = {"done": False}

    root = tk.Tk()
    root.title("Fluent")
    root.configure(bg=BG)
    root.resizable(False, False)
    _center(root)
    root.lift()
    root.attributes("-topmost", True)
    root.after(300, lambda: root.attributes("-topmost", False))

    current: list[tk.Frame] = []

    def _show(ScreenClass, **kwargs):
        for w in current:
            w.destroy()
        current.clear()
        s = ScreenClass(root, **kwargs)
        s.pack(fill="both", expand=True)
        current.append(s)
        root.geometry(f"{WIN_W}x{WIN_H}")

    def _finish():
        result["done"] = True
        root.destroy()

    _show(AuthScreen, on_success=lambda: _show(SetupScreen, on_success=_finish))
    root.mainloop()
    return result["done"]


def needs_onboarding() -> bool:
    return get_token() is None
