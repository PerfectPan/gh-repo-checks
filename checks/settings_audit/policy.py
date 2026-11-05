"""Validate data-only policy files and merge repository overrides."""

import copy
import re

REPO_FIELDS = {"allow_merge_commit", "allow_squash_merge", "allow_rebase_merge",
               "delete_branch_on_merge", "allow_auto_merge"}
BRANCH_FIELDS = {"strict", "require_pull_request", "required_approvals",
                 "require_code_owner_reviews", "require_last_push_approval",
                 "require_conversation_resolution", "require_linear_history",
                 "allow_force_pushes", "allow_deletions", "enforce_admins",
                 "required_checks"}
CI_FIELDS = {"workflows", "required_pr_events", "skip_draft", "no_default_branch_push"}
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
WORKFLOW_RE = re.compile(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml\Z")


def validate_policy(policy, override=False):
    if not isinstance(policy, dict):
        raise ValueError("policy must be an object")
    allowed = {"repository", "branch", "private_ci", "decision_required", "pending_fields", "ruleset_bypasses"}
    if not override:
        allowed |= {"version", "overrides"}
        if policy.get("version") != 1:
            raise ValueError("policy version must be 1")
    if set(policy) - allowed:
        raise ValueError("unknown policy key")
    for group, fields in (("repository", REPO_FIELDS), ("branch", BRANCH_FIELDS),
                          ("private_ci", CI_FIELDS)):
        values = policy.get(group, {})
        if not isinstance(values, dict) or set(values) - fields:
            raise ValueError("unknown or invalid " + group + " policy")
        for key, value in values.items():
            if key in {"required_checks", "workflows", "required_pr_events"}:
                if value is not None and (not isinstance(value, list) or
                        not all(isinstance(v, str) and v for v in value)):
                    raise ValueError(key + " must be a list of strings or null")
                if key == "workflows" and value is not None and any(
                        not WORKFLOW_RE.fullmatch(v) for v in value):
                    raise ValueError("workflow paths must be .github/workflows/*.yml or *.yaml")
            elif key == "required_approvals":
                if type(value) is not int or not 0 <= value <= 6:
                    raise ValueError("required_approvals must be an integer from 0 to 6")
            elif type(value) is not bool:
                raise ValueError(key + " must be boolean")
    if "decision_required" in policy and (not isinstance(policy["decision_required"], list)
            or not all(isinstance(s, str) and s for s in policy["decision_required"])):
        raise ValueError("decision_required must be a list of messages")
    if "pending_fields" in policy and (not isinstance(policy["pending_fields"], list)
            or not all(v in {"branch." + f for f in BRANCH_FIELDS} for v in policy["pending_fields"])):
        raise ValueError("pending_fields must name supported branch fields")
    bypasses = policy.get("ruleset_bypasses", {})
    allowed_rules = {"pull_request", "deletion", "non_fast_forward", "required_linear_history", "required_status_checks"}
    if not isinstance(bypasses, dict) or set(bypasses) - allowed_rules:
        raise ValueError("ruleset_bypasses must name supported rule types")
    for rule_type, actors in bypasses.items():
        if actors is None:
            continue
        if not isinstance(actors, list):
            raise ValueError("ruleset_bypasses values must be actor lists or null")
        for actor in actors:
            if (not isinstance(actor, dict) or set(actor) != {"actor_type", "actor_id", "bypass_mode"}
                    or actor["actor_type"] != "User" or type(actor["actor_id"]) is not int
                    or actor["actor_id"] <= 0 or not isinstance(actor["bypass_mode"], str)
                    or actor["bypass_mode"] not in {"always", "pull_request"}):
                raise ValueError("approved bypass actors must be exact User IDs with an explicit bypass mode")
    overrides = policy.get("overrides", {})
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be an object")
    for repo, values in overrides.items():
        if not REPO_RE.fullmatch(repo):
            raise ValueError("override repository must be OWNER/REPO")
        validate_policy(values, override=True)


def merged_policy(policy, repo):
    result = copy.deepcopy(policy)
    overrides = result.pop("overrides", {})
    for name, values in overrides.items():
        if name.lower() == repo.lower():
            for group, value in values.items():
                if isinstance(value, dict):
                    result.setdefault(group, {}).update(value)
                else:
                    result[group] = value
    return result
