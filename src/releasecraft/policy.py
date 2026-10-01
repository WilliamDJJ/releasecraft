"""Versioned, explicit policy configuration; no project code is evaluated."""

from __future__ import annotations
import json
from pathlib import Path
from .safety import ReleaseError, relative

VERSION = "1.0"
DEFAULT = {
    "schema": 1,
    "mode": "source",
    "include": [],
    "exclude": [],
    "resources": [],
    "external": {},
    "dynamic_resources": {},
    "commands": [],
    "claims": [],
    "third_party": {},
    "reviewed_dynamic": {},
    "notebook_outputs": "strip",
    "max_file_bytes": 16777216,
}


def load_policy(path=None, value=None):
    raw = json.loads(Path(path).read_text("utf-8")) if path else (value or {})
    if not isinstance(raw, dict) or set(raw) - set(DEFAULT):
        raise ReleaseError("Unknown policy field")
    p = {**DEFAULT, **raw}
    if p["mode"] == "research" and "notebook_outputs" not in raw:
        p["notebook_outputs"] = "preserve"
    if p["schema"] != 1 or p["mode"] not in ("source", "runtime", "research"):
        raise ReleaseError("Unsupported policy schema or mode")
    for k in ("include", "exclude", "resources"):
        if not isinstance(p[k], list) or any(not isinstance(s, str) for s in p[k]):
            raise ReleaseError("Invalid policy list")
        for s in p[k]:
            relative(s.replace("*", "glob").replace("?", "q"))
    if p["notebook_outputs"] not in ("strip", "preserve"):
        raise ReleaseError("Invalid Notebook policy")
    if (
        type(p["max_file_bytes"]) is not int
        or not 1024 <= p["max_file_bytes"] <= 128 * 1024 * 1024
    ):
        raise ReleaseError("Invalid file scan limit")
    for k in ("external", "dynamic_resources", "third_party", "reviewed_dynamic"):
        if not isinstance(p[k], dict):
            raise ReleaseError("Invalid policy mapping")
        for key, item in p[k].items():
            relative(key)
            if k == "dynamic_resources":
                if not isinstance(item, list) or not item:
                    raise ReleaseError(
                        "Dynamic resources require bounded explicit paths"
                    )
                for s in item:
                    relative(s.replace("*", "glob").replace("?", "q"))
            elif not isinstance(item, dict) or not item.get("reason"):
                raise ReleaseError("Evidence reason is required")
    for item in p["third_party"].values():
        if not item.get("license") or not item.get("source"):
            raise ReleaseError("Third-party license and source evidence required")
    for item in p["external"].values():
        if (
            set(item) != {"reason", "instructions", "sha256"}
            or not item["instructions"]
            or len(item["sha256"]) != 64
        ):
            raise ReleaseError(
                "External resources need reason, instructions and expected SHA-256"
            )
    if not isinstance(p["commands"], list) or not isinstance(p["claims"], list):
        raise ReleaseError("Commands and claims must be lists")
    ids = set()
    for cmd in p["commands"]:
        if (
            not isinstance(cmd, dict)
            or set(cmd) - {"id", "argv", "timeout"}
            or not isinstance(cmd.get("id"), str)
        ):
            raise ReleaseError("Invalid command")
        argv = cmd.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(s, str) and s and "\x00" not in s for s in argv)
        ):
            raise ReleaseError("Command argv is required")
        if cmd["id"] in ids:
            raise ReleaseError("Duplicate command ID")
        ids.add(cmd["id"])
        if (
            type(cmd.get("timeout", 60)) is not int
            or not 1 <= cmd.get("timeout", 60) <= 600
        ):
            raise ReleaseError("Invalid timeout")
    for claim in p["claims"]:
        if (
            not isinstance(claim, dict)
            or set(claim) != {"description", "commands"}
            or not claim["description"]
            or not isinstance(claim["commands"], list)
            or not claim["commands"]
            or any(x not in ids for x in claim["commands"])
        ):
            raise ReleaseError("Claims must map to actual validation commands")
    return p
