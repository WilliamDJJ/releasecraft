"""Explainable local-state and generated-output evidence, never name-only cleanup.

No project commands or agent configuration are executed. See docs/AI_PROJECTS.md
for rule sources, precedence, override behavior and remaining review decisions.
"""
import json
from pathlib import PurePosixPath
import re
import tomllib

from .safety import placeholder

PRIVATE_FILES = {'.claude/settings.local.json', '.codex/auth.json', '.codex/history.jsonl'}
PRIVATE_TREES = ('.codex/sessions/', 'playwright/.auth/')
SHARED_FILES = {'.claude/settings.json', '.codex/config.toml'}


def private_state(path):
    if '.git' in PurePosixPath(path).parts:
        return True
    framed = '/' + path
    return any(framed.endswith('/' + name) for name in PRIVATE_FILES) or any('/' + prefix in framed for prefix in PRIVATE_TREES)


def shared_agent_file(path):
    return path in SHARED_FILES or (path.startswith('.cursor/rules/') and PurePosixPath(path).suffix in ('.md', '.mdc'))


def agent_config_safe(path, data):
    """Shared configuration is source, but credential values are not approvals."""
    if path not in SHARED_FILES:
        return True
    try:
        value = tomllib.loads(data.decode('utf8')) if path.endswith('.toml') else json.loads(data)
        if not isinstance(value, dict):
            return False
        stack = [value]
        visited = 0
        while stack:
            item = stack.pop()
            visited += 1
            if visited > 10000:
                return False
            if isinstance(item, dict):
                for key, val in item.items():
                    normalized = re.sub(r'[^a-z0-9]', '', key.lower())
                    if any(word in normalized for word in ('password', 'passwd', 'apikey', 'accesstoken', 'authtoken', 'authorization', 'secretkey', 'npmtoken')) and isinstance(val, str) and val and not placeholder(val):
                        return False
                    if isinstance(val, (dict, list)):
                        stack.append(val)
            elif isinstance(item, list):
                stack.extend(item)
        return True
    except (ValueError, UnicodeError, RecursionError):
        return False


def playwright_context(files):
    """Identify projects using Playwright; config values themselves are not executed."""
    contexts = {}
    for path in sorted(files):
        if PurePosixPath(path).name != 'package.json':
            continue
        try:
            obj = json.loads(files[path].content())
            dependencies = {**obj.get('dependencies', {}), **obj.get('devDependencies', {})}
            if '@playwright/test' not in dependencies:
                continue
        except (ValueError, TypeError, AttributeError):
            continue
        parent = PurePosixPath(path).parent
        configs = [str(parent / ('playwright.config.' + ext)) for ext in ('js', 'ts', 'mjs', 'cjs')]
        configs = [name for name in configs if name in files]
        if len(configs) == 1:
            # Arbitrary JS can compute settings; suggest review instead of guessing
            # whether any standard-looking directory is really the active outputDir.
            contexts[str(parent)] = configs[0]
    return contexts


def context_rule(path, files, contexts):
    """Return (category, reason); generated ambiguity requires a human decision."""
    if private_state(path):
        return 'private', 'private-repository-metadata' if '.git' in PurePosixPath(path).parts else 'private-agent-or-auth-state'
    if shared_agent_file(path):
        return 'shared', 'shared-agent-instructions'
    if path.endswith('/AGENTS.md') or path in ('AGENTS.md', 'CLAUDE.md'):
        return 'shared', 'shared-agent-instructions'
    for base in contexts:
        root = PurePosixPath(base)
        if not PurePosixPath(path).is_relative_to(root):
            continue
        local = PurePosixPath(path).relative_to(root)
        for i, part in enumerate(local.parts[:-1]):
            if part.endswith('-snapshots'):
                test = str(root.joinpath(*local.parts[:i], part[:-10]))
                if test in files and PurePosixPath(test).suffix in ('.js', '.ts', '.mjs', '.cjs'):
                    return 'shared', 'playwright-baseline-input'
        if local.parts[0] in ('test-results', 'playwright-report'):
            return 'review', 'generated-test-output-review'
    if path.endswith('.log'):
        return 'generated', 'transient-artifact'
    # General reports, screenshots, test/debug scripts, dist/ and archives have
    # no reliable generated-only meaning. Existing source/resource rules apply.
    return None, None
