"""Command-line interface shared with the local UI."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from . import __version__
from .analyze import analyze, freeze, plan_diff
from .build import assemble, verify_archive
from .policy import load_policy
from .diagnostics import plan_summary
from .safety import ReleaseError, atomic_json, canonical
from .validate import validate
from .streaming import SpaceError


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="releasecraft", description="Prepare reproducible, gated source releases"
    )
    parser.add_argument(
        "--version", action="version", version=f"releasecraft {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("analyze", "plan"):
        p = sub.add_parser(name)
        p.add_argument("source")
        p.add_argument("--config")
        if name == "plan":
            p.add_argument("--work", required=True)
            p.add_argument(
                "--details", action="store_true",
                help="Also print full private evidence instead of the grouped summary",
            )
    p = sub.add_parser("review-policy", help="Export the current reviewed policy from a frozen plan")
    p.add_argument("plan")
    p.add_argument("--output", required=True)
    p = sub.add_parser("build")
    p.add_argument("source")
    p.add_argument("--plan", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("diff")
    p.add_argument("before")
    p.add_argument("after")
    p = sub.add_parser("verify")
    p.add_argument("archive")
    p.add_argument("--report")
    p = sub.add_parser("validate")
    p.add_argument("archive")
    p.add_argument("--backend", choices=("docker", "trusted"), default="docker")
    p.add_argument("--image")
    p.add_argument("--wheelhouse")
    p.add_argument("--trust-project", action="store_true")
    p.add_argument("--report")
    p = sub.add_parser("serve")
    p.add_argument("--source", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--port", type=int, default=8765)
    p = sub.add_parser("gui", help="Open the native desktop window")
    p.add_argument("--source", default="")
    args = parser.parse_args(argv)
    try:
        if args.command in ("analyze", "plan"):
            policy = load_policy(args.config)
            result = (
                freeze(args.source, args.work, policy)
                if args.command == "plan"
                else analyze(args.source, policy)
            )
        elif args.command == "review-policy":
            from .review import review_policy
            policy = review_policy(json.loads(Path(args.plan).read_text("utf8")))
            with Path(args.output).open("xb") as target:
                target.write(canonical(policy))
            result = {"status": "EXPORTED", "detail": "Review the policy before sharing; unchanged decisions do not approve unresolved files."}
        elif args.command == "build":
            result = assemble(
                args.source, json.loads(Path(args.plan).read_text("utf8")), args.output
            )
        elif args.command == "diff":
            result = plan_diff(
                *(
                    json.loads(Path(p).read_text("utf8"))
                    for p in (args.before, args.after)
                )
            )
        elif args.command == "verify":
            result = verify_archive(args.archive)
        elif args.command == "validate":
            result = validate(
                args.archive,
                args.backend,
                args.image,
                args.trust_project,
                args.wheelhouse,
            )
        elif args.command == "gui":
            from .desktop import main as desktop_main

            return desktop_main(["--source", args.source])
        else:
            from .web import serve

            serve(args.source, args.work, args.port)
            return 0
        if getattr(args, "report", None):
            atomic_json(args.report, result)
        displayed = (
            plan_summary(result)
            if args.command == "plan" and not args.details
            else result
        )
        sys.stdout.buffer.write(canonical(displayed))
        return (
            0
            if result.get("status") in (None, "PLANNED", "READY", "EXPORTED")
            else (3 if result.get("status") == "CANDIDATE" else 2)
        )
    except SpaceError:
        print(json.dumps({"status": "BLOCKED", "error": "insufficient-disk-space"}))
        return 2
    except (ReleaseError, OSError, ValueError, KeyError, TypeError):
        # Exception strings may contain sensitive paths or source content.
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "error": "Operation rejected. Check paths, policy, plan and safety gates.",
                }
            )
        )
        return 2
