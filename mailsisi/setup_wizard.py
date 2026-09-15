"""The little setup window, so nobody has to hand-edit config files.

It takes the mailbox login, download folder and schedule, then writes .env (the
password) and settings.yaml (everything about this machine) next to the app. It
can test the login first and tick itself into the logon task. Which senders and
manufacturers to expect stays in config.yaml - that's prepared per client and
never touched from here.
"""

import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import yaml

from . import tasks

# email domain -> (IMAP server, port), used to fill the server in for people
PROVIDERS = {
    "gmail.com":      ("imap.gmail.com", "993"),
    "googlemail.com": ("imap.gmail.com", "993"),
    "outlook.com":    ("outlook.office365.com", "993"),
    "hotmail.com":    ("outlook.office365.com", "993"),
    "live.com":       ("outlook.office365.com", "993"),
    "msn.com":        ("outlook.office365.com", "993"),
    "office365.com":  ("outlook.office365.com", "993"),
    "yahoo.com":      ("imap.mail.yahoo.com", "993"),
    "aol.com":        ("imap.aol.com", "993"),
    "icloud.com":     ("imap.mail.me.com", "993"),
    "me.com":         ("imap.mail.me.com", "993"),
    "mac.com":        ("imap.mail.me.com", "993"),
    "fastmail.com":   ("imap.fastmail.com", "993"),
}

# where each provider hands out app passwords
APP_PASSWORD_HELP = {
    "gmail.com":      "https://myaccount.google.com/apppasswords",
    "googlemail.com": "https://myaccount.google.com/apppasswords",
    "yahoo.com":      "https://login.yahoo.com/account/security/app-passwords",
    "aol.com":        "https://login.aol.com/account/security/app-passwords",
    "icloud.com":     "https://support.apple.com/102654",
    "me.com":         "https://support.apple.com/102654",
    "mac.com":        "https://support.apple.com/102654",
    "fastmail.com":   "https://www.fastmail.help/hc/en-us/articles/1500000278342",
}

def _domain(addr: str) -> str:
    return addr.split("@", 1)[1].strip().lower() if "@" in addr else ""

def _help_url(addr: str) -> str:
    d = _domain(addr)
    if d in APP_PASSWORD_HELP:
        return APP_PASSWORD_HELP[d]
    if d:
        return f"https://www.google.com/search?q={d}+IMAP+app+password"
    return "https://support.google.com/mail/answer/185833"

def _read_env(home: Path) -> dict:
    """Existing IMAP_* values, so re-opening the window shows what's set."""
    out = {}
    env_path = home / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                out[key.strip()] = val.strip()
    return out

def _read_settings(home: Path) -> dict:
    settings_path = home / "settings.yaml"
    if settings_path.exists():
        try:
            return yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}

def _write_env(home: Path, host, port, user, pwd) -> None:
    lines = [
        "# Written by MailSISI setup. Holds passwords - do not share or commit.",
        f"IMAP_HOST={host}",
        f"IMAP_PORT={port}",
        f"IMAP_USERNAME={user}",
        f"IMAP_PASSWORD={pwd}",
        "# SMTP mirrors IMAP; only used if responder.send is true in config.yaml.",
        f"SMTP_USERNAME={user}",
        f"SMTP_PASSWORD={pwd}",
        "",
    ]
    (home / ".env").write_text("\n".join(lines), encoding="utf-8")

def _write_settings(home: Path, output_dir, poll_interval, since_days, since_date) -> None:
    # write since_days/since_date out even when blank (as null) so they override
    # whatever config.yaml says. A fixed date beats the rolling window; see
    # _since_date in processor.py.
    settings = {
        "output_dir": output_dir,
        "superseded_dir": str(Path(output_dir) / "_superseded"),
        "poll_interval": int(poll_interval),
        "since_days": int(since_days) if since_days else None,
        "since_date": since_date or None,
    }
    with open(home / "settings.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(settings, f, sort_keys=False)

def _try_login(host, port, user, pwd) -> None:
    from imap_tools import MailBox
    with MailBox(host, int(port)).login(user, pwd):
        pass

def show_done(output_dir: str, count: int) -> None:
    """Popup after a run started from the window, so a double-click gets a real
    answer instead of a console flashing past."""
    root = tk.Tk()
    root.withdraw()
    where = f"\n\nFiles are saved under:\n{output_dir}" if output_dir else ""
    messagebox.showinfo("MailSISI", f"Finished. {count} new file(s) downloaded.{where}")
    root.destroy()

def run_wizard(home: Path) -> str:
    """Show the window. Returns 'start', 'close' or 'cancel'."""
    env = _read_env(home)
    settings = _read_settings(home)
    result = {"action": "cancel"}

    root = tk.Tk()
    root.title("MailSISI Setup")
    root.resizable(False, False)
    frm = ttk.Frame(root, padding=14)
    frm.grid()
    pad = {"padx": 8, "pady": 4}

    ttk.Label(frm, text="Connect MailSISI to your email inbox.",
              font=("Segoe UI", 11, "bold")).grid(
        column=0, row=0, columnspan=3, sticky="w", pady=(0, 10))

    ttk.Label(frm, text="Email address").grid(column=0, row=1, sticky="e", **pad)
    e_user = ttk.Entry(frm, width=34)
    e_user.grid(column=1, row=1, columnspan=2, sticky="w", **pad)

    ttk.Label(frm, text="Password / App Password").grid(column=0, row=2, sticky="e", **pad)
    e_pwd = ttk.Entry(frm, width=34, show="*")
    e_pwd.grid(column=1, row=2, sticky="w", **pad)
    ttk.Button(frm, text="How?", width=6,
               command=lambda: webbrowser.open(_help_url(e_user.get()))).grid(
        column=2, row=2, sticky="w", **pad)

    ttk.Label(frm, text="Download folder").grid(column=0, row=3, sticky="e", **pad)
    e_dir = ttk.Entry(frm, width=34)
    e_dir.grid(column=1, row=3, sticky="w", **pad)

    def browse():
        chosen = filedialog.askdirectory()
        if chosen:
            e_dir.delete(0, tk.END)
            e_dir.insert(0, chosen)

    ttk.Button(frm, text="Browse", width=6, command=browse).grid(
        column=2, row=3, sticky="w", **pad)

    ttk.Label(frm, text="Check every (seconds)").grid(column=0, row=4, sticky="e", **pad)
    e_poll = ttk.Entry(frm, width=12)
    e_poll.grid(column=1, row=4, sticky="w", **pad)

    ttk.Label(frm, text="Read emails from the last (days)").grid(
        column=0, row=5, sticky="e", **pad)
    e_days = ttk.Entry(frm, width=12)
    e_days.grid(column=1, row=5, sticky="w", **pad)
    ttk.Label(frm, text="rolling; e.g. 30 = only recent mail",
              foreground="#666").grid(column=2, row=5, sticky="w", **pad)

    ttk.Label(frm, text="Or on/after date (YYYY-MM-DD)").grid(
        column=0, row=6, sticky="e", **pad)
    e_since = ttk.Entry(frm, width=14)
    e_since.grid(column=1, row=6, sticky="w", **pad)
    ttk.Label(frm, text="override for old files; blank = use rolling",
              foreground="#666").grid(column=2, row=6, sticky="w", **pad)

    ttk.Label(frm, text="IMAP server").grid(column=0, row=7, sticky="e", **pad)
    e_host = ttk.Entry(frm, width=22)
    e_host.grid(column=1, row=7, sticky="w", **pad)
    ttk.Label(frm, text="Port").grid(column=0, row=8, sticky="e", **pad)
    e_port = ttk.Entry(frm, width=8)
    e_port.grid(column=1, row=8, sticky="w", **pad)

    def fill_server(_event=None):
        """Guess the server and port from the address, if we know the provider."""
        host, port = PROVIDERS.get(_domain(e_user.get()), (None, None))
        if host:
            e_host.delete(0, tk.END)
            e_host.insert(0, host)
            e_port.delete(0, tk.END)
            e_port.insert(0, port)

    e_user.bind("<FocusOut>", fill_server)

    autostart = tk.BooleanVar(value=False)
    ttk.Checkbutton(frm, text="Run automatically at logon", variable=autostart).grid(
        column=0, row=9, columnspan=3, sticky="w", **pad)

    # fill in what's already configured, otherwise sensible defaults
    e_user.insert(0, env.get("IMAP_USERNAME", ""))
    e_pwd.insert(0, env.get("IMAP_PASSWORD", ""))
    e_dir.insert(0, settings.get("output_dir", ""))
    e_poll.insert(0, str(settings.get("poll_interval", 300)))
    days = settings.get("since_days")
    e_days.insert(0, str(days) if days else "")
    since = settings.get("since_date")
    e_since.insert(0, str(since) if since else "")
    e_host.insert(0, env.get("IMAP_HOST", "imap.gmail.com"))
    e_port.insert(0, env.get("IMAP_PORT", "993"))

    def gather():
        return (e_host.get().strip(), e_port.get().strip(), e_user.get().strip(),
                e_pwd.get(), e_dir.get().strip(), e_poll.get().strip(),
                e_days.get().strip(), e_since.get().strip())

    def looks_ok(host, port, user, pwd, out, poll):
        if not all([host, port, user, pwd, out, poll]):
            messagebox.showwarning("Missing info", "Please fill in every field.")
            return False
        try:
            int(port)
            int(poll)
        except ValueError:
            messagebox.showwarning("Invalid number", "Port and interval must be whole numbers.")
            return False
        return True

    def on_test():
        host, port, user, pwd, *_ = gather()
        if not all([host, port, user, pwd]):
            messagebox.showwarning("Missing info", "Enter server, port, address, and password first.")
            return
        root.config(cursor="wait")
        root.update()
        try:
            _try_login(host, port, user, pwd)
            messagebox.showinfo("Success", "Connected to the mailbox successfully.")
        except Exception as e:
            messagebox.showerror("Connection failed", f"Could not log in:\n\n{e}")
        finally:
            root.config(cursor="")

    def save(action):
        host, port, user, pwd, out, poll, days, since = gather()
        if not looks_ok(host, port, user, pwd, out, poll):
            return
        if days:
            try:
                int(days)
            except ValueError:
                messagebox.showwarning("Invalid number", "Days must be a whole number.")
                return
        try:
            _write_env(home, host, port, user, pwd)
            _write_settings(home, out, poll, days, since)
        except Exception as e:
            messagebox.showerror("Could not save", str(e))
            return
        if autostart.get():
            try:
                tasks.install_task()
            except Exception as e:
                messagebox.showerror(
                    "Autostart failed",
                    f"Settings were saved, but registering autostart failed:\n\n{e}")
        result["action"] = action
        root.destroy()

    btns = ttk.Frame(frm)
    btns.grid(column=0, row=10, columnspan=3, pady=(12, 0))
    ttk.Button(btns, text="Test connection", command=on_test).grid(column=0, row=0, padx=4)
    ttk.Button(btns, text="Save & Start", command=lambda: save("start")).grid(column=1, row=0, padx=4)
    ttk.Button(btns, text="Save & Close", command=lambda: save("close")).grid(column=2, row=0, padx=4)
    ttk.Button(btns, text="Cancel", command=root.destroy).grid(column=3, row=0, padx=4)

    root.mainloop()
    return result["action"]
