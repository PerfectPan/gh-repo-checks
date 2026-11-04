"""Conservative static checks for explicitly selected private CI workflows."""

import re


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


def audit_private_ci(snapshot, policy, metadata, add):
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
