# MailSISI - Version 1.0

MailSISI watches an email inbox and automatically saves, renames, and sorts the
file attachments your distributors send, turning a monthly pile of manual
spreadsheet downloads into something that runs by itself.

It connects over IMAP, takes attachments only from a whitelist of distributor
senders, works out which manufacturer each file belongs to, and files it
accordingly. When a distributor emails a corrected version, that file replaces
the old one and the previous version is kept aside. Nothing on the mail server
is ever actually changed: no deleting, moving, or marking as read. Every run
remembers what it already handled, so running it twice costs nothing.

Python, SQLite, IMAP, Tkinter, packaged with PyInstaller. No Python needed on the
machine that runs it.

### How it decides things

- **Which files** — a per-distributor sender whitelist, filtered on the mail
  server so the rest of the inbox is never read, plus an extension allowlist.
- **Which manufacturer** — checks the subject, then the filename, then the domain
  of any outside recipient, then the body; exact matches first, then a fuzzy pass
  so typos still resolve. Anything unmatched is filed under `unknown`.
- **Which version** — attachments are hashed, so identical bytes are never saved
  twice, and replies are tied to their original through the email threading
  headers, which is what lets a correction supersede the right file.
- **Where it goes** — configurable grouping (by distributor, conversation,
  manufacturer, or month) and a naming template, both set in `config.yaml`.

Copy `config.example.yaml` to `config.yaml` and list your own distributors there;
everything else is set through the setup window. To run from source:
`pip install -r requirements.txt`, then `python downloader.py`.

---

The rest of this page is the setup walkthrough for the machine that will run it.

## Quick start

1. **Make a folder** like `C:\MailSISI` and drop in the two files you were given:
   **MailSISI.exe** and **config.yaml**. Keep them together.
2. **Get an app password** for the inbox (see step 2 below).
3. **Double-click MailSISI.exe**, fill in the email + app password + download
   folder, tick **Run automatically at logon**, and click **Save & Start**.

That's it. The rest of this page explains each step in more detail.

## What you need

- A Windows PC that stays on — this is the machine that keeps MailSISI running.
- **MailSISI.exe** and **config.yaml** (both provided to you). config.yaml already
  lists your distributors and manufacturers, so you never edit it.
- The email account MailSISI will read, and permission to create an app password
  for it. Gmail, Outlook, Yahoo, iCloud, AOL, and Fastmail all work.

## 1. Put the files in a folder

Create a folder such as `C:\MailSISI` and copy **MailSISI.exe** and
**config.yaml** into it. Keep them together, as MailSISI reads and writes
everything (settings, logs, its file record) in this one folder.

## 2. Get an app password (will be updated to OAuth)

Email providers require a one-time "app password" for apps like this instead of
your normal password (this kicks in whenever two-step verification is on).

**Gmail:**
1. Turn on 2-Step Verification at **https://myaccount.google.com/security**.
2. Open **https://myaccount.google.com/apppasswords**, name it `MailSISI`, click
   **Create**, and copy the 16-letter password.

**Other providers:** click the **How?** button in the setup window (next step) to
open that provider's app-password page. Work/Office 365 accounts may need IT to
allow IMAP sign-in first.

## 3. Run the setup

Double-click **MailSISI.exe**. The **Setup** window opens every time you launch it
this way, pre-filled with the current settings.

> First launch: if Windows shows a blue "unknown publisher" notice, click
> **More info** → **Run anyway**. This happens once.

Fill in:

- **Email address** — the inbox to read. For common providers this auto-fills the
  IMAP server and port; otherwise enter them yourself.
- **Password / App Password** — the app password from step 2, spaces removed.
- **Download folder** — Browse to where saved files should go.
- **Check every** — how often to look, in seconds (`300` = every 5 minutes).
- **Read emails from the last (days)** — a rolling window, e.g. `30` for the last
  month. Old mail drops off automatically.
- **Or on/after date** — leave blank normally. Set a date like `2026-01-01` once
  to pull in older files; it overrides the rolling window until you clear it.

Then:

1. Click **Test connection** → you should see "Connected successfully".
2. Tick **Run automatically at logon** so it keeps running after every restart.
3. Click **Save & Start**.

MailSISI saves your settings, checks the inbox once, downloads any new files, and
shows a popup with how many it saved. Files are sorted into folders by
manufacturer; anything it can't match is filed under `unknown`.

> MailSISI only fetches **new** emails — it remembers what it has already saved.
> Deleting downloaded files does not pull them back.

## Everyday use

Type these into PowerShell opened in the MailSISI folder (in File Explorer: click
the address bar, type `powershell`, press Enter):

- **Change a setting:** `.\MailSISI.exe --setup`
- **See what it did:** open `mailsisi.log` next to the exe.
- **Preview without saving:** `.\MailSISI.exe --dry-run`
- **Stop auto-start:** `.\MailSISI.exe --uninstall-task`

## If something goes wrong

- **Login error** — the app password is wrong, or 2-Step Verification is off.
  Redo step 2 and rerun `--setup`.
- **No files appear** — the start date may be later than the emails you expect, or
  the sender isn't one your config is set up for.
- **Windows blocked the file** — right-click MailSISI.exe → Properties → tick
  **Unblock**.
