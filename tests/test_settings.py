"""Deterministic audit tests: no GitHub access or writes."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("settings", ROOT / "checks/settings.py")
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)


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


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = fixture()
        self.policy = copy.deepcopy(POLICY)

    def result(self, key):
        report = settings.audit(self.snapshot, self.policy)
        return next(f for f in report["findings"] if f["check"] == key)

    def test_baseline_passes(self):
        self.assertEqual(settings.audit(self.snapshot, self.policy)["status"], "pass")

    def test_strict_true_fails(self):
        self.snapshot["classic"]["data"]["required_status_checks"]["strict"] = True
        self.assertEqual(self.result("branch.strict")["status"], "fail")

    def test_403_or_404_is_unknown_not_unprotected(self):
        for reason in ("HTTP 403", "HTTP 404", "network"):
            with self.subTest(reason=reason):
                self.snapshot["classic"] = {"state": "unknown", "reason": reason}
                self.assertEqual(self.result("branch.strict")["status"], "unknown")
                self.assertEqual(self.result("branch.required_checks")["status"], "unknown")

    def test_missing_repository_setting_is_unknown(self):
        del self.snapshot["metadata"]["data"]["allow_auto_merge"]
        self.assertEqual(self.result("repository.allow_auto_merge")["status"], "unknown")

    def test_conflicting_ruleset_fails_even_if_classic_unknown(self):
        self.snapshot["classic"] = {"state": "unknown"}
        self.snapshot["rules"] = ok([{"type": "required_status_checks", "parameters": {
            "strict_required_status_checks_policy": True}}])
        self.assertEqual(self.result("branch.strict")["status"], "fail")

    def test_evaluate_rules_are_not_assumed_active(self):
        self.snapshot["classic"] = ok({})
        self.assertEqual(self.result("branch.require_pull_request")["status"], "fail")

    def test_rules_cannot_hide_extra_approvals(self):
        self.snapshot["rules"] = ok([{"type": "pull_request", "parameters": {
            "required_approving_review_count": 2}}])
        self.assertEqual(self.result("branch.required_approvals")["status"], "fail")

    def test_rules_can_supply_positive_protection(self):
        self.snapshot["classic"] = {"state": "unknown"}
        self.snapshot["rules"] = ok([{"type": "required_linear_history"}])
        self.assertEqual(self.result("branch.require_linear_history")["status"], "pass")

    def test_malformed_contributing_status_rule_is_unknown(self):
        self.snapshot["rules"] = ok([{"type": "required_status_checks", "parameters": {}}])
        self.assertEqual(self.result("branch.required_checks")["status"], "unknown")

    def test_malformed_classic_pr_rule_is_unknown(self):
        self.snapshot["classic"]["data"]["required_pull_request_reviews"] = False
        self.assertEqual(self.result("branch.require_pull_request")["status"], "unknown")

    def test_missing_required_check_names_stay_unknown(self):
        self.policy["branch"]["required_checks"] = None
        self.assertEqual(self.result("branch.required_checks")["status"], "unknown")

    def test_required_checks_compare_union(self):
        self.snapshot["rules"] = ok([{"type": "required_status_checks", "parameters": {
            "strict_required_status_checks_policy": False,
            "required_status_checks": [{"context": "lint"}]}}])
        self.assertEqual(self.result("branch.required_checks")["status"], "fail")
        self.policy["branch"]["required_checks"] = ["lint", "test"]
        self.assertEqual(self.result("branch.required_checks")["status"], "pass")

    def test_hidden_ruleset_bypass_is_unknown(self):
        self.snapshot["rules"] = ok([{"type": "deletion", "ruleset_id": 4}])
        self.snapshot["rulesets"] = {"4": ok({})}
        self.assertEqual(self.result("branch.enforce_admins")["status"], "unknown")

    def test_known_admin_bypass_fails(self):
        self.snapshot["rules"] = ok([{"type": "deletion", "ruleset_id": 4}])
        self.snapshot["rulesets"] = {"4": ok({"bypass_actors": [
            {"actor_type": "RepositoryRole", "actor_id": 5, "bypass_mode": "always"}]})}
        self.assertEqual(self.result("branch.enforce_admins")["status"], "fail")

    def test_pending_exception_is_not_failed_or_approved(self):
        self.policy["pending_fields"] = ["branch.require_pull_request"]
        self.snapshot["classic"]["data"]["required_pull_request_reviews"] = None
        self.assertEqual(self.result("branch.require_pull_request")["status"], "unknown")

    def test_overrides_do_not_mutate_baseline(self):
        self.policy["overrides"] = {"Example/Repository": {"branch": {"required_checks": ["lint"]}}}
        merged = settings.merged_policy(self.policy, "example/repository")
        self.assertEqual(merged["branch"]["required_checks"], ["lint"])
        self.assertEqual(self.policy["branch"]["required_checks"], ["test"])

    def test_policy_rejects_unknown_fields_and_invalid_types(self):
        for policy in ({"version": 1, "apply": True},
                       {"version": 1, "branch": {"strict": "false"}},
                       {"version": 1, "branch": {"required_approvals": True}},
                       {"version": 1, "private_ci": {"workflows": ["../../other.yml"]}}):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                settings.validate_policy(policy)

    def test_get_is_explicit_and_read_only(self):
        response = subprocess.CompletedProcess([], 0, "{}", "")
        with patch.object(settings.subprocess, "run", return_value=response) as run:
            settings.gh_get("repos/example/repository")
        command = run.call_args.args[0]
        self.assertEqual(command[:6], ["gh", "api", "--hostname", "github.com", "--method", "GET"])
        self.assertNotIn("--input", command)
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_error_does_not_echo_credentials(self):
        response = subprocess.CompletedProcess([], 1, "", "secret-not-for-report HTTP 403")
        with patch.object(settings.subprocess, "run", return_value=response):
            result = settings.gh_get("repos/example/repository")
        self.assertNotIn("secret-not-for-report", json.dumps(result))
        self.assertEqual(result["state"], "unknown")

    def test_pagination_flattens_all_pages(self):
        response = subprocess.CompletedProcess([], 0, '[[{"type":"deletion"}], [{"type":"non_fast_forward"}]]', "")
        with patch.object(settings.subprocess, "run", return_value=response) as run:
            result = settings.gh_get("repos/example/repository/rules/branches/main", True)
        self.assertEqual(len(result["data"]), 2)
        self.assertIn("--paginate", run.call_args.args[0])

    def test_cli_unknown_exit_is_two_and_json_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            (p / "policy.json").write_text(json.dumps(POLICY))
            (p / "snapshot.json").write_text(json.dumps({"repo": "example/repository"}))
            result = subprocess.run(["python3", str(ROOT / "checks/settings.py"), "--policy", str(p / "policy.json"),
                                     "--snapshot", str(p / "snapshot.json"), "--json"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "unknown")


class ScopedBypassTest(unittest.TestCase):
    OWNER = {"actor_type": "User", "actor_id": 123, "bypass_mode": "always"}

    def setUp(self):
        self.snapshot = fixture()
        self.snapshot["classic"] = ok({})
        self.snapshot["rules"] = ok([])
        self.snapshot["rulesets"] = {}
        self.policy = {"version": 1, "branch": {"enforce_admins": True},
                       "ruleset_bypasses": {"pull_request": [self.OWNER], "deletion": [],
                                           "non_fast_forward": [], "required_status_checks": [self.OWNER]}}
        self.add_ruleset(1, ["pull_request"], [self.OWNER])
        self.add_ruleset(2, ["deletion", "non_fast_forward"], [])
        self.add_ruleset(3, ["required_status_checks"], [self.OWNER])

    def add_ruleset(self, rid, types, actors):
        self.snapshot["rules"]["data"].extend({"type": t, "ruleset_id": rid} for t in types)
        self.snapshot["rulesets"][str(rid)] = ok({"target": "branch", "enforcement": "active",
             "rules": [{"type": t} for t in types], "bypass_actors": copy.deepcopy(actors)})

    def result(self, key):
        return next(f for f in settings.audit(self.snapshot, self.policy)["findings"] if f["check"] == key)

    def test_exact_owner_pr_and_ci_bypasses_pass_when_split_from_protection(self):
        self.assertEqual(settings.audit(self.snapshot, self.policy)["status"], "pass")

    def test_broad_admin_role_is_not_equivalent_to_owner(self):
        self.snapshot["rulesets"]["1"]["data"]["bypass_actors"] = [
            {"actor_type": "RepositoryRole", "actor_id": 5, "bypass_mode": "always"}]
        self.assertEqual(self.result("ruleset_bypasses.pull_request")["status"], "fail")
        self.assertEqual(self.result("branch.enforce_admins")["status"], "fail")

    def test_other_user_is_not_authorized(self):
        self.snapshot["rulesets"]["1"]["data"]["bypass_actors"][0]["actor_id"] = 456
        self.assertEqual(self.result("ruleset_bypasses.pull_request")["status"], "fail")

    def test_pr_only_mode_does_not_grant_direct_push(self):
        self.snapshot["rulesets"]["1"]["data"]["bypass_actors"][0]["bypass_mode"] = "pull_request"
        self.assertEqual(self.result("ruleset_bypasses.pull_request")["status"], "fail")

    def test_owner_bypass_cannot_extend_to_deletion(self):
        self.snapshot["rulesets"]["1"]["data"]["rules"].append({"type": "deletion"})
        self.assertEqual(self.result("ruleset_bypasses.pull_request")["status"], "fail")

    def test_owner_bypass_cannot_extend_to_force_push(self):
        self.snapshot["rulesets"]["1"]["data"]["rules"].append({"type": "non_fast_forward"})
        self.assertEqual(self.result("ruleset_bypasses.pull_request")["status"], "fail")

    def test_missing_ruleset_details_remain_unknown(self):
        self.snapshot["rulesets"]["1"] = {"state": "unknown", "reason": "HTTP 403"}
        self.assertEqual(self.result("ruleset_bypasses.pull_request")["status"], "unknown")

    def test_hidden_rule_scope_remains_unknown(self):
        del self.snapshot["rulesets"]["1"]["data"]["rules"]
        self.assertEqual(self.result("ruleset_bypasses.pull_request")["status"], "unknown")

    def test_undecided_ci_bypass_is_not_inferred(self):
        self.policy["ruleset_bypasses"]["required_status_checks"] = None
        self.assertEqual(self.result("ruleset_bypasses.required_status_checks")["status"], "unknown")
        self.assertEqual(self.result("branch.enforce_admins")["status"], "unknown")

    def test_classic_pr_rule_still_needs_overlap_review(self):
        self.snapshot["classic"]["data"]["required_pull_request_reviews"] = {}
        self.assertEqual(self.result("owner_direct_push.classic_overlap")["status"], "unknown")

    def test_classic_status_checks_still_need_overlap_review(self):
        self.snapshot["classic"]["data"]["required_status_checks"] = {"strict": False, "contexts": ["test"]}
        self.assertEqual(self.result("owner_direct_push.classic_ci_overlap")["status"], "unknown")
        self.assertEqual(settings.audit(self.snapshot, self.policy)["status"], "unknown")

    def test_malformed_ruleset_body_is_unknown_not_a_crash(self):
        self.snapshot["rulesets"]["1"] = ok([])
        self.assertEqual(self.result("ruleset_bypasses.pull_request")["status"], "unknown")
        self.assertEqual(self.result("branch.enforce_admins")["status"], "unknown")

    def test_actual_user_id_types_are_not_coerced(self):
        for actor_id in ("123", True, None, {"id": 123}):
            with self.subTest(actor_id=actor_id):
                self.snapshot["rulesets"]["1"]["data"]["bypass_actors"][0]["actor_id"] = actor_id
                self.assertEqual(self.result("ruleset_bypasses.pull_request")["status"], "unknown")

    def test_malformed_ruleset_envelope_is_unknown(self):
        self.snapshot["rulesets"]["1"] = []
        self.assertEqual(self.result("ruleset_bypasses.pull_request")["status"], "unknown")
        self.assertEqual(self.result("branch.enforce_admins")["status"], "unknown")

    def test_malformed_ruleset_map_is_unknown(self):
        self.snapshot["rulesets"] = []
        self.assertEqual(self.result("ruleset_bypasses.pull_request")["status"], "unknown")
        self.assertEqual(self.result("branch.enforce_admins")["status"], "unknown")

    def test_policy_rejects_role_substitution(self):
        self.policy["ruleset_bypasses"]["pull_request"] = [
            {"actor_type": "RepositoryRole", "actor_id": 5, "bypass_mode": "always"}]
        with self.assertRaises(ValueError):
            settings.validate_policy(self.policy)


class WorkflowTest(unittest.TestCase):
    def inspect(self, text, **overrides):
        found = []
        policy = {"required_pr_events": ["opened", "synchronize", "ready_for_review"],
                  "skip_draft": True, "no_default_branch_push": True}
        policy.update(overrides)
        settings.audit_workflow("ci.yml", text, policy,
            lambda key, status, *args, **kwargs: found.append((key.rsplit(".", 1)[-1], status)), "main")
        return dict(found)

    def workflow(self, events="pull_request:\n    types: [opened, synchronize, ready_for_review]", guard="if: ${{ !github.event.pull_request.draft }}"):
        return f"name: CI\non:\n  {events}\njobs:\n  test:\n    {guard}\n    runs-on: ubuntu-latest\n    steps: []\n"

    def test_ready_non_draft_configuration_passes(self):
        result = self.inspect(self.workflow())
        self.assertEqual(result.pop("execution"), "unknown")
        self.assertEqual(set(result.values()), {"pass"})

    def test_implicit_default_events_miss_ready(self):
        self.assertEqual(self.inspect(self.workflow("pull_request:"))["pr_events"], "fail")

    def test_missing_job_guard_fails(self):
        self.assertEqual(self.inspect(self.workflow(guard=""))["test"], "fail")

    def test_guard_literal_whitespace_is_not_removed(self):
        guard = "if: ${{ github.event_name != 'pull_request ' || !github.event.pull_request.draft }}"
        self.assertEqual(self.inspect(self.workflow(guard=guard))["test"], "unknown")

    def test_complex_guard_stays_unknown(self):
        self.assertEqual(self.inspect(self.workflow(guard="if: ${{ inputs.run_ci }}"))["test"], "unknown")

    def test_push_to_main_fails(self):
        self.assertEqual(self.inspect(self.workflow("push:\n    branches: [main]"))["no_default_branch_push"], "fail")

    def test_push_tags_only_does_not_run_main(self):
        self.assertEqual(self.inspect(self.workflow("push:\n    tags: ['v*']"))["no_default_branch_push"], "pass")

    def test_push_other_branch_passes(self):
        self.assertEqual(self.inspect(self.workflow("push:\n    branches: [release]"))["no_default_branch_push"], "pass")

    def test_push_complex_globs_stay_unknown(self):
        self.assertEqual(self.inspect(self.workflow("push:\n    branches: ['release/**']"))["no_default_branch_push"], "unknown")

    def test_paths_filters_need_review(self):
        self.assertEqual(self.inspect(self.workflow("pull_request:\n    types: [opened, synchronize, ready_for_review]\n    paths: ['src/**']"))["filters"], "unknown")

    def test_malformed_yaml_is_unknown(self):
        self.assertEqual(self.inspect("on: ["), {"parse": "unknown"})


if __name__ == "__main__":
    unittest.main()
