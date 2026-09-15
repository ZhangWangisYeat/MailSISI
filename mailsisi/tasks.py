"""Run-at-logon registration via the Windows Task Scheduler. Used by the setup
window's 'Run automatically' tick box and by --install-task / --uninstall-task."""

import subprocess
import sys
from pathlib import Path

TASK_NAME = "MailSISI"

def _target() -> str:
    """What the task actually runs: the exe in daemon mode when packaged, python
    on downloader.py when running from source."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" --daemon'
    script = Path(__file__).resolve().parent.parent / "downloader.py"
    return f'"{sys.executable}" "{script}" --daemon'

def install_task() -> None:
    """Create or replace the logon task. Raises with schtasks' output if it fails."""
    subprocess.run(
        ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", _target(),
         "/SC", "ONLOGON", "/RL", "LIMITED", "/F"],
        check=True, capture_output=True, text=True,
    )

def uninstall_task() -> None:
    subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        check=True, capture_output=True, text=True,
    )
