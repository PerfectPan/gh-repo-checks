"""Compare branch protections and aggregate classic/effective rules."""

from .bypasses import admin_enforcement, audit_bypasses
from .github import source


def audit_branch(snapshot, policy, add, compare):
    classic = source(snapshot, "classic", dict)
    rules = source(snapshot, "rules", list)
    if rules is not None and not all(isinstance(r, dict) for r in rules):
        rules = None
    complete = classic is not None and rules is not None
    rules_by_type = {}
    for rule in rules or []:
        rules_by_type.setdefault(rule.get("type"), []).append(rule)
    prs = rules_by_type.get("pull_request", [])
    statuses = rules_by_type.get("required_status_checks", [])
    cpr = classic.get("required_pull_request_reviews") if classic else None
    cstatus = classic.get("required_status_checks") if classic else None

    def enabled(key):
        value = classic.get(key) if classic is not None else None
        return value.get("enabled") if isinstance(value, dict) else value

    def protective(classic_key, rule_type):
        if enabled(classic_key) is True or rules_by_type.get(rule_type):
            return True
        return False if complete else None

    def all_values(cfield, rfield, collection, cobject, expected):
        values = []
        malformed = cobject is not None and not isinstance(cobject, dict)
        if isinstance(cobject, dict):
            value = cobject.get(cfield)
            malformed = value is None
            values.append(value)
        for rule in collection:
            params = rule.get("parameters")
            value = params.get(rfield) if isinstance(params, dict) else None
            malformed |= value is None
            values.append(value)
        known = [v for v in values if v is not None]
        # A conflicting rule remains a conflict even if another source is unreadable.
        if any(v != expected for v in known):
            return next(v for v in known if v != expected)
        if not complete or malformed or not values:
            return None
        return expected

    bp = policy.get("branch", {})
    for key, expected in bp.items():
        if "branch." + key in policy.get("pending_fields", []):
            add("branch." + key, "unknown", detail="Policy exception is awaiting a decision; no requirement is inferred.")
            continue
        detail = "Classic protection and all active effective rules are inspected; unreadable sources are unknown."
        if key == "strict":
            actual = all_values("strict", "strict_required_status_checks_policy", statuses, cstatus, expected)
        elif key == "require_pull_request":
            actual = True if isinstance(cpr, dict) or prs else None if cpr is not None else False if complete else None
        elif key == "required_approvals":
            actual = all_values("required_approving_review_count", "required_approving_review_count", prs, cpr, expected)
        elif key in {"require_code_owner_reviews", "require_last_push_approval"}:
            rule_key = "require_code_owner_review" if key == "require_code_owner_reviews" else key
            actual = all_values(key, rule_key, prs, cpr, expected)
        elif key == "require_conversation_resolution":
            actual = enabled("required_conversation_resolution")
            if any(isinstance(r.get("parameters"), dict) and r["parameters"].get("required_review_thread_resolution") is True for r in prs):
                actual = True
            if actual is not True:
                actual = False if complete else None
        elif key == "require_linear_history":
            actual = protective("required_linear_history", "required_linear_history")
        elif key in {"allow_force_pushes", "allow_deletions"}:
            rule_type = "non_fast_forward" if key == "allow_force_pushes" else "deletion"
            value = enabled(key)
            actual = False if value is False or rules_by_type.get(rule_type) else True if complete else None
        elif key == "enforce_admins":
            actual = admin_enforcement(snapshot, policy, classic, rules)
            detail = "Known admin bypass is drift. Hidden or actor-specific bypass exceptions need review."
        elif key == "required_checks":
            if expected is None:
                add("branch." + key, "unknown", detail="Identify actual required CI job contexts for this repository before setting the policy.")
                continue
            names = set()
            malformed = False
            if isinstance(cstatus, dict):
                contexts = cstatus.get("contexts")
                checks = cstatus.get("checks", [])
                if not isinstance(contexts, list) or not all(isinstance(n, str) for n in contexts):
                    malformed = True
                else:
                    names.update(contexts)
                if not isinstance(checks, list) or not all(isinstance(c, dict) and isinstance(c.get("context"), str) for c in checks):
                    malformed = True
                else:
                    names.update(c["context"] for c in checks)
            elif cstatus is not None:
                malformed = True
            for r in statuses:
                params = r.get("parameters")
                checks = params.get("required_status_checks") if isinstance(params, dict) else None
                if not isinstance(checks, list) or not all(isinstance(c, dict) and isinstance(c.get("context"), str) for c in checks):
                    malformed = True
                else:
                    names.update(c["context"] for c in checks)
            actual = sorted(names) if complete and not malformed else None
            expected = sorted(expected)
            detail = "Exact union of configured context names; app binding and workflow execution still need verification."
        compare("branch." + key, expected, actual, detail)

    audit_bypasses(snapshot, policy, classic, rules, add, compare)
