"""Install the bundled wheel without network access or global package changes."""

from pathlib import Path
import subprocess
import sys
import venv


def main():
    if sys.version_info < (3, 11):
        raise SystemExit("Releasecraft requires Python 3.11 or newer.")
    root = Path(__file__).resolve().parent
    wheels = sorted((root / "wheels").glob("releasecraft-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("Expected exactly one bundled Releasecraft wheel.")
    target = root / ".venv"
    if target.exists():
        raise SystemExit(
            ".venv already exists. Use a fresh extracted distribution to install safely."
        )
    # POSIX interpreter symlinks preserve the base runtime's shared-library lookup.
    # Windows keeps copied executables and does not require symlink privileges.
    venv.EnvBuilder(with_pip=True, symlinks=sys.platform != "win32").create(target)
    python = target / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            str(wheels[0]),
        ],
        check=True,
        timeout=120,
    )
    subprocess.run(
        [str(python), "-m", "releasecraft", "--version"], check=True, timeout=15
    )
    print("Installed locally. Run the platform launcher with --help to get started.")


if __name__ == "__main__":
    main()
