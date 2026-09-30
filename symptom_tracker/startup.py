"""Start with Windows via a shortcut in the user's Startup folder."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import APP_DIR

LAUNCHER = APP_DIR / "Symptom Tracker.pyw"
SHORTCUT = (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu"
            / "Programs" / "Startup" / "Symptom Tracker.lnk")


def _pythonw():
    # pyw.exe is the launcher Windows uses when a .pyw file is double-clicked.
    found = shutil.which("pyw")
    if found:
        return found
    return str(Path(sys.executable).with_name("pythonw.exe"))


def is_enabled():
    return SHORTCUT.exists()


def enable():
    def q(s):
        return "'" + str(s).replace("'", "''") + "'"
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(" + q(SHORTCUT) + ");"
        f"$s.TargetPath = {q(_pythonw())};"
        f"$s.Arguments = {q(chr(34) + str(LAUNCHER) + chr(34) + ' --minimized')};"
        f"$s.WorkingDirectory = {q(APP_DIR)};"
        "$s.Description = 'Symptom Tracker';"
        "$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   check=True, capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def disable():
    SHORTCUT.unlink(missing_ok=True)
