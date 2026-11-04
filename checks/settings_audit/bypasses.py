"""Evaluate exact-user bypasses across the whole applicable ruleset."""


def scoped_bypass(rule, snapshot, policy):
    """Check the whole active ruleset; a bypass never applies to just one rule."""
    entries = snapshot.get("rulesets")
    entry = entries.get(str(rule.get("ruleset_id"))) if isinstance(entries, dict) else None
    if not isinstance(entry, dict):
        return None
    data = entry.get("data", {})
    if entry.get("state") != "ok" or not isinstance(data, dict):
        return None
    actors = data.get("bypass_actors")
    rules = data.get("rules")
    if (data.get("enforcement") != "active" or data.get("target") != "branch"
            or not isinstance(actors, list) or not isinstance(rules, list) or not rules
            or not all(isinstance(r, dict) and isinstance(r.get("type"), str) for r in rules)
            or not all(isinstance(a, dict) and all(k in a for k in ("actor_type", "actor_id", "bypass_mode")) for a in actors)):
        return None
    scope = {r["type"] for r in rules}
    if rule.get("type") not in scope:
        return None
    for actor in actors:
        if (not isinstance(actor["actor_type"], str) or not isinstance(actor["bypass_mode"], str)
                or actor["actor_type"] not in {"User", "Team", "Integration", "RepositoryRole", "OrganizationAdmin", "DeployKey"}
                or actor["bypass_mode"] not in {"always", "pull_request", "exempt"}):
            return None
        valid_id = type(actor["actor_id"]) is int and actor["actor_id"] > 0
        if not valid_id and not (actor["actor_type"] in {"OrganizationAdmin", "DeployKey"} and actor["actor_id"] is None):
            return None
    def normalize(values):
        return sorted(((a["actor_type"], a["actor_id"], a["bypass_mode"]) for a in values),
                      key=lambda actor: (actor[0], repr(actor[1]), actor[2]))
    unknown = False
    for rule_type in scope:
        expected = policy.get("ruleset_bypasses", {}).get(rule_type)
        if expected is None:
            unknown = True
        elif normalize(actors) != normalize(expected):
            return False
    return None if unknown else True


def admin_enforcement(snapshot, policy, classic, rules):
    """Compare admin enforcement without broadening any approved bypass."""
    complete = classic is not None and rules is not None
    value = classic.get("enforce_admins") if classic else None
    actual = value.get("enabled") if isinstance(value, dict) else value
    bypass_known = rules is not None
    for rule in rules or []:
        entries = snapshot.get("rulesets")
        entry = entries.get(str(rule.get("ruleset_id")), {}) if isinstance(entries, dict) else {}
        entry = entry if isinstance(entry, dict) else {}
        data = entry.get("data", {})
        actors = data.get("bypass_actors") if entry.get("state") == "ok" and isinstance(data, dict) else None
        if not isinstance(actors, list):
            bypass_known = False
        elif actors and rule.get("type") in policy.get("ruleset_bypasses", {}):
            accepted = scoped_bypass(rule, snapshot, policy)
            if accepted is False:
                actual = False
                break
            if accepted is None:
                bypass_known = False
        elif any(a.get("actor_type") == "OrganizationAdmin" or
                 (a.get("actor_type") == "RepositoryRole" and a.get("actor_id") == 5)
                 for a in actors if isinstance(a, dict)):
            actual = False
            break
        elif actors:
            bypass_known = False
    if actual is not False and (not complete or not bypass_known):
        actual = None
    elif actual is None and complete:
        actual = bool(rules)
    return actual


def audit_bypasses(snapshot, policy, classic, rules, add, compare):
    """Audit exact actor scope and independent classic-protection overlap."""
    rules_by_type = {}
    for rule in rules or []:
        rules_by_type.setdefault(rule.get("type"), []).append(rule)
    cpr = classic.get("required_pull_request_reviews") if classic else None
    cstatus = classic.get("required_status_checks") if classic else None
    for rule_type, expected in policy.get("ruleset_bypasses", {}).items():
        if expected is None:
            add("ruleset_bypasses." + rule_type, "unknown", detail="Bypass for this rule type has not been decided; no bypass is authorized by this policy.")
            continue
        matching = rules_by_type.get(rule_type, [])
        values = [scoped_bypass(r, snapshot, policy) for r in matching]
        actual = False if False in values else None if rules is None or None in values else bool(values)
        compare("ruleset_bypasses." + rule_type, True, actual,
                "Every applicable rule must have the exact approved actor list across its entire ruleset; no broader role or hidden rule is accepted.")
    if policy.get("ruleset_bypasses", {}).get("pull_request"):
        add("owner_direct_push.classic_overlap", "unknown" if classic is None or cpr is not None else "pass",
            detail="A ruleset bypass does not bypass classic PR protection. Inspect any classic allowances before claiming direct pushes work.")

    if policy.get("ruleset_bypasses", {}).get("required_status_checks"):
        add("owner_direct_push.classic_ci_overlap", "unknown" if classic is None or cstatus is not None else "pass",
            detail="A ruleset CI bypass does not bypass classic required status checks. Inspect classic enforcement before claiming the owner can bypass CI.")
