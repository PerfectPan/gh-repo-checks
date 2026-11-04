"""Collect GitHub evidence through explicit GET requests only."""

import base64
import json
import os
import re
import subprocess
from urllib.parse import quote


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
