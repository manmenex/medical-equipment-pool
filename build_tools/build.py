"""
Convenience build script - wraps the PyInstaller spec so a developer can
just run:

    python build_tools/build.py

instead of remembering the full `pyinstaller ... build.spec` invocation.
Produces `dist/MedicalDeviceRecallMonitor/` containing the frozen app.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_FILE = Path(__file__).resolve().parent / "build.spec"


def main() -> int:
    cmd = [sys.executable, "-m", "PyInstaller", str(SPEC_FILE), "--noconfirm"]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    if result.returncode != 0:
        print("Build failed.", file=sys.stderr)
        return result.returncode

    print(
        "\nBuild complete: dist/MedicalDeviceRecallMonitor/\n"
        "Remember to also install a Playwright browser next to the build "
        "(one-time, not bundled by PyInstaller):\n"
        "    python -m playwright install chromium\n"
        "See docs/INSTALL.md for full packaging/deployment notes."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
