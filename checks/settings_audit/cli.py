"""Read-only GitHub settings audit. Configuration and snapshots are data only."""

import argparse
import json
from pathlib import Path

from .audit import audit
from .github import collect
from .policy import REPO_RE, merged_policy, validate_policy


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, type=Path)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--repo")
    inputs.add_argument("--snapshot", type=Path, help="Audit saved read-only responses without network access")
    parser.add_argument("--json", action="store_true", help="Print machine-readable results")
    args = parser.parse_args(argv)
    try:
        policy = json.loads(args.policy.read_text())
        validate_policy(policy)
        snapshot = json.loads(args.snapshot.read_text()) if args.snapshot else None
        repo = snapshot.get("repo") if isinstance(snapshot, dict) else args.repo
        if not isinstance(repo, str) or not REPO_RE.fullmatch(repo):
            raise ValueError("repository must use OWNER/REPO format")
        policy = merged_policy(policy, repo)
        if snapshot is None:
            snapshot = collect(repo, policy)
        report = audit(snapshot, policy)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report["repo"] + ": " + report["status"] + " (read-only)")
        for item in report["findings"]:
            print("{status:7} {check}: expected={expected!r} actual={actual!r} {detail}".format(**item))
    return {"pass": 0, "fail": 1, "unknown": 2}[report["status"]]
