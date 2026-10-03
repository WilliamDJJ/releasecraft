"""Persist exact, human-reviewed file decisions without copying source contents."""
import copy

from .analyze import verify_plan
from .policy import load_policy
from .safety import ReleaseError


def review_policy(plan):
    verify_plan(plan)
    return copy.deepcopy(plan['policy'])


def decide(plan, policy, path, action, reason):
    verify_plan(plan)
    row = next((r for r in plan['files'] if r['path'] == path), None)
    if row is None or row['kind'] != 'file':
        raise ReleaseError('Review a regular file from this plan')
    if action == 'include' and (row.get('findings') or row['reason'] in (
            'sensitive-content', 'private-environment', 'private-agent-or-auth-state', 'private-repository-metadata',
            'third-party-provenance', 'agent-config-needs-review', 'npm-config-needs-review',
            'parser-file-limit', 'invalid-notebook', 'analysis-incomplete')):
        raise ReleaseError('File requires a source, safety or provenance correction')
    result = copy.deepcopy(policy)
    result['decisions'][path] = {'action': action, 'reason': reason, 'sha256': row['sha256']}
    return load_policy(value=result)
