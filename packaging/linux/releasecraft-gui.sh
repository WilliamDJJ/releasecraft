#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ ! -x "$ROOT/.venv/bin/python" ]; then
    printf '%s\n' 'Run sh install.sh first. Python 3.11+ and tkinter are required.' >&2
    exit 2
fi
if ! "$ROOT/.venv/bin/python" -c 'import tkinter' 2>/dev/null; then
    printf '%s\n' 'Install the Python Tk package provided by your Linux distribution, then run this launcher again.' >&2
    exit 2
fi
exec "$ROOT/.venv/bin/python" -m releasecraft.desktop "$@"
