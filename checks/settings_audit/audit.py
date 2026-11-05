"""Assemble repository, branch, and CI findings into one read-only report."""

from .branches import audit_branch
from .github import source
from .workflows import audit_private_ci


def audit(snapshot, policy):
    findings = []

    def add(key, state, expected=None, actual=None, detail=""):
        findings.append(dict(check=key, status=state, expected=expected, actual=actual, detail=detail))

    def compare(key, expected, actual, detail=""):
        add(key, "unknown" if actual is None else "pass" if type(actual) is type(expected) and actual == expected else "fail",
            expected, actual, detail)

    metadata = source(snapshot, "metadata", dict)
    for key, expected in policy.get("repository", {}).items():
        actual = metadata.get(key) if metadata else None
        compare("repository." + key, expected, actual)
    for decision in policy.get("decision_required", []):
        add("policy.decision_required", "unknown", detail=decision)

    audit_branch(snapshot, policy, add, compare)
    audit_private_ci(snapshot, policy, metadata, add)
    statuses_seen = {f["status"] for f in findings}
    overall = "fail" if "fail" in statuses_seen else "unknown" if "unknown" in statuses_seen or not findings else "pass"
    return {"repo": snapshot.get("repo"), "branch": snapshot.get("branch"), "status": overall,
            "read_only": True, "findings": findings}
