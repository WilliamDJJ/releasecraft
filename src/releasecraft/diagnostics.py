"""Bounded private evidence and deterministic, path-free action summaries."""

from collections import Counter


class EvidenceLimit(Exception):
    """Internal control flow: never treat a global limit as a per-file error."""


class EvidenceBudget:
    def __init__(self, limit):
        self.limit = limit
        self.retained = 0
        self.omitted_at_least = 0

    def take(self):
        if self.retained >= self.limit:
            self.omitted_at_least += 1
            raise EvidenceLimit()
        self.retained += 1

    def items(self, values=()):
        result = EvidenceList(self)
        result.extend(values)
        return result


class EvidenceList(list):
    def __init__(self, budget):
        super().__init__()
        self.budget = budget

    def append(self, value):
        self.budget.take()
        super().append(value)

    def extend(self, values):
        for value in values:
            self.append(value)

    def __iadd__(self, values):
        self.extend(values)
        return self


def next_action(code):
    if code.startswith(("scan-", "analysis-")):
        return "Choose a smaller coherent component root and analyze it again; this plan is incomplete."
    if code in ("missing-license", "license-needs-review", "license-excluded"):
        return "Supply or review the component's release license; a policy override cannot replace permission."
    if code == "sensitive-content":
        return "Remove the detected secret or private content from selected source, then analyze again."
    if code == "npm-config-needs-review":
        return "Keep only documented literal npm preferences in project configuration; move credentials and machine-specific settings outside selected source. Inclusion overrides cannot approve unsupported npm configuration."
    if code in ("missing-resource", "explicit-resource-missing", "dependency-not-included"):
        return "Fix the missing resource or its declaration, or choose the component root containing it."
    if code.startswith("dynamic-") or code in ("absolute-resource", "unclassified-resource", "binary-needs-classification"):
        return "Choose a coherent component root and provide explicit resource/workflow declarations where needed."
    if code == "third-party-provenance":
        return "Provide third-party source and license evidence before inclusion."
    if code in ("unsafe-or-unreadable-file", "unreadable-directory"):
        return "Review the path identifier in the local plan and use readable regular files without links or reparse points."
    return "Review the retained private evidence and correct the source or its explicit declarations."


def blocker_summary(blockers, complete):
    counts = Counter(item["code"] for item in blockers)
    return {
        "retained_details": len(blockers),
        "counts_complete": complete,
        "count_scope": "retained blocker details; incomplete scans may have additional unknown blockers",
        "groups": [
            {"code": code, "count": count, "next_action": next_action(code)}
            for code, count in sorted(counts.items())
        ],
    }


def plan_summary(plan):
    """The full evidence remains in the work directory's unmodified plan.json."""
    return {
        "schema": plan["schema"],
        "status": plan["status"],
        "plan_sha256": plan["plan_sha256"],
        "snapshot_sha256": plan["snapshot_sha256"],
        "snapshot_scope": plan["snapshot_scope"],
        "file_states": dict(sorted(Counter(row["state"] for row in plan["files"]).items())),
        "scan": plan["scan"],
        "analysis": plan["analysis"],
        "blocker_summary": plan["blocker_summary"],
        "private_evidence": "The --work directory contains plan.json; --details also prints it. Do not publish private evidence without review.",
    }
