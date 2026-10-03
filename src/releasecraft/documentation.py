"""Factual README generation from observed metadata and declared validation claims."""

import json
import shlex
import subprocess
import tomllib


def draft_readme(files, policy):
    if not policy["commands"] or not policy["claims"]:
        return None
    title = "Project source release"
    description = "Source code, maintenance files and declared validation workflows."
    if "pyproject.toml" in files:
        try:
            project = tomllib.loads(files["pyproject.toml"].content().decode("utf8")).get(
                "project", {}
            )
            title = str(project.get("name", title))
            description = str(project.get("description", description))
        except (ValueError, TypeError):
            pass
    elif "package.json" in files:
        try:
            project = json.loads(files["package.json"].content())
            title = str(project.get("name", title))
            description = str(project.get("description", description))
        except (ValueError, TypeError):
            pass
    lines = ["# " + title, "", description, "", "## Declared behavior", ""]
    lines += ["- " + c["description"] for c in policy["claims"]]
    lines += ["", "## Setup", ""]
    if "pyproject.toml" in files:
        lines += [
            "Use the Python version and dependencies declared in `pyproject.toml`.",
            "Install in a fresh virtual environment with `python -m pip install .`.",
        ]
    elif "package.json" in files:
        lines += [
            "Use Node.js and the dependencies declared in `package.json`.",
            "Install with `npm ci` when a package lock is present, otherwise `npm install`.",
        ]
    else:
        lines += [
            "Use the interpreter and dependencies required by the source and commands below.",
            "No automatic dependency installation procedure has been inferred.",
        ]
    lines += [
        "",
        "## Validation commands",
        "",
        "Run from the repository root. These are declared checks, not claims of completed validation.",
    ]
    for command in policy["commands"]:
        lines += [
            "",
            "### " + command["id"],
            "",
            "POSIX shell:",
            "",
            "```sh",
            shlex.join(command["argv"]),
            "```",
            "",
            "Windows command line:",
            "",
            "```text",
            subprocess.list2cmdline(command["argv"]),
            "```",
        ]
    lines += [
        "",
        "## Release boundaries",
        "",
        "Consult the external SHA-256-bound validation report for actual outcomes and tested platforms.",
        "Configuration templates, resources, and project license files retain their original terms.",
        "This source release does not imply permission to redistribute external datasets or models.",
        "",
    ]
    return "\n".join(lines).encode("utf8")
