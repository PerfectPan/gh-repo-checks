#!/usr/bin/env python3
"""Read-only GitHub settings audit. Configuration and snapshots are data only."""

import argparse
import base64
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote


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


def gh_get(endpoint, paginated=False):
    """The only external command in this audit: an explicit GET to github.com."""
    command = ["gh", "api", "--hostname", "github.com", "--method", "GET",
               "-H", "Accept: application/vnd.github+json",
               "-H", "X-GitHub-Api-Version: 2022-11-28", endpoint]
    if paginated:
        command += ["--paginate", "--slurp"]
    env = dict(os.environ, GH_PROMPT_DISABLED="1", GH_PAGER="cat")
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=60, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {"state": "unknown", "reason": "gh unavailable or read timed out"}
    if result.returncode:
        # Never repeat raw stderr: authentication helpers may include secrets.
        status = re.search(r"HTTP (\d{3})", result.stderr)
        reason = "GitHub GET failed" + (" (HTTP " + status[1] + ")" if status else "")
        return {"state": "unknown", "reason": reason}
    try:
        data = json.loads(result.stdout)
        if paginated:
            if not isinstance(data, list) or not all(isinstance(p, list) for p in data):
                raise ValueError("invalid page")
            data = [item for page in data for item in page]
        return {"state": "ok", "data": data}
    except (ValueError, TypeError):
        return {"state": "unknown", "reason": "GitHub returned invalid JSON or pages"}


def collect(repo, policy):
    base = "repos/" + repo
    metadata = gh_get(base)
    snapshot = {"repo": repo, "metadata": metadata, "workflows": []}
    data = metadata.get("data", {})
    branch = data.get("default_branch") if isinstance(data, dict) else None
    if not isinstance(branch, str) or not branch:
        return snapshot
    snapshot["branch"] = branch
    encoded = quote(branch, safe="")
    snapshot["classic"] = gh_get(base + "/branches/" + encoded + "/protection")
    snapshot["rules"] = gh_get(base + "/rules/branches/" + encoded + "?per_page=100", True)
    snapshot["rulesets"] = {}
    rules = snapshot["rules"].get("data", [])
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rid = rule.get("ruleset_id")
            if type(rid) is int and str(rid) not in snapshot["rulesets"]:
                snapshot["rulesets"][str(rid)] = gh_get(base + "/rulesets/" + str(rid))
    if data.get("private") is True and policy.get("private_ci"):
        paths = policy["private_ci"].get("workflows")
        snapshot["workflow_scope"] = "explicit" if paths else "unresolved"
        for path in paths or []:
            response = gh_get(base + "/contents/" + path + "?ref=" + encoded)
            entry = {"path": path, "state": "unknown"}
            content = response.get("data", {})
            if response["state"] == "ok" and isinstance(content, dict) and content.get("encoding") == "base64":
                try:
                    entry.update(state="ok", text=base64.b64decode(content["content"], validate=False).decode("utf-8"))
                except (KeyError, ValueError, UnicodeError):
                    pass
            snapshot["workflows"].append(entry)
    return snapshot


def source(snapshot, key, kind):
    item = snapshot.get(key, {})
    if isinstance(item, dict) and item.get("state") == "ok" and isinstance(item.get("data"), kind):
        return item["data"]
    return None


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
            # Per-source configuration check, not proof that a particular actor cannot bypass.
            actual = enabled("enforce_admins") if classic else None
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

    ci = policy.get("private_ci", {})
    if ci:
        if metadata is None or type(metadata.get("private")) is not bool:
            add("private_ci", "unknown", detail="Repository visibility is unreadable.")
        elif metadata["private"]:
            paths = ci.get("workflows")
            if not paths:
                add("private_ci.scope", "unknown", detail="List this repository's CI workflows explicitly; no workflow is assumed to be CI.")
            else:
                by_path = {w.get("path"): w for w in snapshot.get("workflows", []) if isinstance(w, dict)}
                for path in paths:
                    workflow = by_path.get(path, {})
                    if workflow.get("state") != "ok" or not isinstance(workflow.get("text"), str):
                        add("private_ci." + path, "unknown", detail="Workflow unavailable.")
                    else:
                        audit_workflow(path, workflow["text"], ci, add, snapshot.get("branch"))
    statuses_seen = {f["status"] for f in findings}
    overall = "fail" if "fail" in statuses_seen else "unknown" if "unknown" in statuses_seen or not findings else "pass"
    return {"repo": snapshot.get("repo"), "branch": snapshot.get("branch"), "status": overall,
            "read_only": True, "findings": findings}


def audit_workflow(path, text, policy, add, default_branch):
    prefix = "private_ci." + path + "."
    try:
        import yaml
    except ImportError:
        add(prefix + "parse", "unknown", detail="Optional PyYAML is unavailable; do not infer workflow behavior from text matching.")
        return
    try:
        # BaseLoader keeps GitHub's 'on' key from becoming YAML 1.1 boolean True.
        doc = yaml.load(text, Loader=yaml.BaseLoader)
        if not isinstance(doc, dict):
            raise ValueError("not an object")
    except (yaml.YAMLError, ValueError, RecursionError):
        add(prefix + "parse", "unknown", detail="Workflow YAML cannot be safely interpreted.")
        return
    events = doc.get("on", {})
    if isinstance(events, str):
        events = {events: {}}
    elif isinstance(events, list):
        events = {event: {} for event in events if isinstance(event, str)}
    if not isinstance(events, dict):
        add(prefix + "events", "unknown", detail="Unrecognized trigger configuration.")
        return
    if policy.get("no_default_branch_push"):
        state = "pass"
        push = events.get("push")
        if "push" in events:
            state = "fail"
            if isinstance(push, dict):
                branches = push.get("branches")
                ignored = push.get("branches-ignore")
                if branches is None and ignored is None and ("tags" in push or "tags-ignore" in push):
                    state = "pass"
                elif isinstance(branches, list) and isinstance(default_branch, str):
                    if default_branch in branches or "**" in branches or "*" in branches:
                        state = "fail"
                    elif all(isinstance(b, str) and not re.search(r"[*!?\[\]+]", b) for b in branches):
                        state = "pass"
                    else:
                        state = "unknown"
                elif isinstance(ignored, list) and default_branch in ignored:
                    state = "pass"
                elif branches is not None or ignored is not None:
                    state = "unknown"
        add(prefix + "no_default_branch_push", state, True, state == "pass" if state != "unknown" else None,
            "Checks whether a default-branch push can trigger this workflow; complex globs need review.")
    required = set(policy.get("required_pr_events") or [])
    if required:
        trigger = events.get("pull_request")
        configured = trigger.get("types") if isinstance(trigger, dict) else None
        types = configured if configured is not None else ["opened", "synchronize", "reopened"]
        good = "pull_request" in events and isinstance(types, list) and required.issubset(types)
        add(prefix + "pr_events", "pass" if good else "fail", sorted(required), types)
        if isinstance(trigger, dict) and set(trigger) & {"paths", "paths-ignore", "branches", "branches-ignore"}:
            add(prefix + "filters", "unknown", detail="Trigger filters can prevent required checks; verify them against required job contexts.")
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        add(prefix + "jobs", "unknown", detail="No interpretable jobs.")
        return
    if policy.get("skip_draft"):
        for name, job in jobs.items():
            condition = job.get("if") if isinstance(job, dict) else None
            if condition is None:
                add(prefix + "draft." + name, "fail", detail="Job lacks a job-level Draft PR guard.")
                continue
            normalized = re.sub(r"'[^']*'|\"[^\"]*\"|\s+", lambda m: m[0] if m[0][0] in "'\"" else "", str(condition))
            if normalized.startswith("${{") and normalized.endswith("}}"):
                normalized = normalized[3:-2]
            supported = {"!github.event.pull_request.draft", "github.event.pull_request.draft==false",
                         "github.event_name!='pull_request'||!github.event.pull_request.draft",
                         "github.event_name!='pull_request'||github.event.pull_request.draft==false"}
            state = "pass" if normalized in supported else "unknown"
            if "pull_request_target" in events:
                state = "unknown"
            add(prefix + "draft." + name, state, detail="Only a small set of job-level guards is proven. Complex conditions require review.")
    add(prefix + "execution", "unknown", detail="Static configuration only. Verify actual non-Draft PR job runs and reusable/conditional execution paths at the exact commit.")


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


if __name__ == "__main__":
    sys.exit(main())
