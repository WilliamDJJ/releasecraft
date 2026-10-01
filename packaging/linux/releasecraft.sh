#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ ! -x "$ROOT/.venv/bin/python" ]; then
    printf '%s\n' 'Run sh install.sh first.' >&2
    exit 2
fi
exec "$ROOT/.venv/bin/python" -m releasecraft "$@"
