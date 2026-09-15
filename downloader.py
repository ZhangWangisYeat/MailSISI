"""
MailSISI - distributor data intake.

Reads an IMAP mailbox, saves the attachments whitelisted distributors send,
renames and files them by distributor and manufacturer, and lets a corrected
file in a reply replace the version it corrects without re-downloading anything
that hasn't changed. It can draft acknowledgements too.

    python downloader.py                  setup window, then run on Save & Start
    python downloader.py --setup          setup window only
    python downloader.py --daemon         keep polling in the background, no window
    python downloader.py --dry-run        show what would happen, write nothing
    python downloader.py --install-task   run at logon
    python downloader.py --uninstall-task stop running at logon
    python downloader.py --config other.yaml
"""

import argparse
import sys
import time

from mailsisi import tasks
from mailsisi.config import base_dir, load_config, setup_logging
from mailsisi.db import open_db
from mailsisi.matching import build_sender_map
from mailsisi.processor import run_once

def _run(cfg, daemon: bool, dry_run: bool) -> int:
    """Returns how many files were saved (0 in daemon mode)."""
    logger = setup_logging(cfg)
    sender_map = build_sender_map(cfg.get("senders", []))
    conn = open_db(cfg["db_path"])

    if daemon:
        interval = cfg.get("poll_interval", 300)
        logger.info(f"Daemon mode: polling every {interval}s (Ctrl+C to stop)")
        while True:
            try:
                run_once(cfg, conn, sender_map, logger, dry_run)
            except KeyboardInterrupt:
                logger.info("Stopped.")
                break
            except Exception as e:
                logger.error(f"Error during poll: {e}", exc_info=True)
            time.sleep(interval)
        return 0
    return run_once(cfg, conn, sender_map, logger, dry_run)

def main() -> None:
    parser = argparse.ArgumentParser(description="MailSISI distributor data intake")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--daemon", action="store_true", help="Poll continuously in the background, no window")
    parser.add_argument("--dry-run", action="store_true", help="Preview only; no writes, no window")
    parser.add_argument("--setup", action="store_true", help="Open the setup window")
    parser.add_argument("--install-task", action="store_true", help="Register to run at logon")
    parser.add_argument("--uninstall-task", action="store_true", help="Remove the logon task")
    args = parser.parse_args()

    if args.install_task:
        tasks.install_task()
        print(f"Registered '{tasks.TASK_NAME}' to run at logon.")
        return
    if args.uninstall_task:
        tasks.uninstall_task()
        print(f"Removed the '{tasks.TASK_NAME}' logon task.")
        return

    # No window for the headless flags: --daemon is what the logon task uses,
    # --dry-run is for poking around from a terminal.
    if args.daemon or args.dry_run:
        try:
            cfg = load_config(args.config)
            _run(cfg, daemon=args.daemon, dry_run=args.dry_run)
        except Exception as e:
            print(f"Fatal error: {e}", file=sys.stderr)
            sys.exit(1)
        return

    # Everything else, a double-click included, opens the setup window first so
    # the settings can be looked over, then runs once on Save & Start.
    from mailsisi.setup_wizard import run_wizard, show_done
    if run_wizard(base_dir()) != "start":
        return  # cancelled, or saved without running

    try:
        cfg = load_config(args.config)
        saved = _run(cfg, daemon=False, dry_run=False)
        show_done(cfg.get("output_dir", ""), saved)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
