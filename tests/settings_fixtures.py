"""Shared deterministic fixtures for settings audit tests."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "checks"))


def ok(data):
    return {"state": "ok", "data": data}


def fixture():
    return {"repo": "example/repository", "branch": "main", "metadata": ok({
        "private": True, "default_branch": "main", "allow_merge_commit": False,
        "allow_squash_merge": True, "allow_rebase_merge": True,
        "delete_branch_on_merge": True, "allow_auto_merge": False}),
        "classic": ok({"required_status_checks": {"strict": False, "contexts": ["test"]},
                       "required_pull_request_reviews": {"required_approving_review_count": 0,
                           "require_code_owner_reviews": False, "require_last_push_approval": False},
                       "enforce_admins": {"enabled": True},
                       "required_linear_history": {"enabled": True},
                       "required_conversation_resolution": {"enabled": True},
                       "allow_force_pushes": {"enabled": False},
                       "allow_deletions": {"enabled": False}}),
        "rules": ok([]), "workflows": []}


POLICY = {"version": 1, "repository": {"allow_merge_commit": False,
    "allow_squash_merge": True, "allow_rebase_merge": True,
    "delete_branch_on_merge": True, "allow_auto_merge": False},
    "branch": {"strict": False, "require_pull_request": True,
        "required_approvals": 0, "require_code_owner_reviews": False,
        "require_last_push_approval": False, "require_conversation_resolution": True,
        "require_linear_history": True, "allow_force_pushes": False,
        "allow_deletions": False, "enforce_admins": True, "required_checks": ["test"]}}
