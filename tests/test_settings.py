"""Offline regression tests; no GitHub access or writes."""

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from settings_fixtures import POLICY, ROOT, fixture, ok
from settings_audit.audit import audit
from settings_audit import github
from settings_audit.policy import merged_policy, validate_policy


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = fixture()
        self.policy = copy.deepcopy(POLICY)

    def result(self, key):
        report = audit(self.snapshot, self.policy)
        return next(f for f in report["findings"] if f["check"] == key)

    def test_baseline_passes(self):
        self.assertEqual(audit(self.snapshot, self.policy)["status"], "pass")

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
        merged = merged_policy(self.policy, "example/repository")
        self.assertEqual(merged["branch"]["required_checks"], ["lint"])
        self.assertEqual(self.policy["branch"]["required_checks"], ["test"])

    def test_policy_rejects_unknown_fields_and_invalid_types(self):
        for policy in ({"version": 1, "apply": True},
                       {"version": 1, "branch": {"strict": "false"}},
                       {"version": 1, "branch": {"required_approvals": True}},
                       {"version": 1, "private_ci": {"workflows": ["../../other.yml"]}}):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                validate_policy(policy)

    def test_get_is_explicit_and_read_only(self):
        response = subprocess.CompletedProcess([], 0, "{}", "")
        with patch.object(github.subprocess, "run", return_value=response) as run:
            github.gh_get("repos/example/repository")
        command = run.call_args.args[0]
        self.assertEqual(command[:6], ["gh", "api", "--hostname", "github.com", "--method", "GET"])
        self.assertNotIn("--input", command)
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_error_does_not_echo_credentials(self):
        response = subprocess.CompletedProcess([], 1, "", "secret-not-for-report HTTP 403")
        with patch.object(github.subprocess, "run", return_value=response):
            result = github.gh_get("repos/example/repository")
        self.assertNotIn("secret-not-for-report", json.dumps(result))
        self.assertEqual(result["state"], "unknown")

    def test_pagination_flattens_all_pages(self):
        response = subprocess.CompletedProcess([], 0, '[[{"type":"deletion"}], [{"type":"non_fast_forward"}]]', "")
        with patch.object(github.subprocess, "run", return_value=response) as run:
            result = github.gh_get("repos/example/repository/rules/branches/main", True)
        self.assertEqual(len(result["data"]), 2)
        self.assertIn("--paginate", run.call_args.args[0])

    def test_cli_runs_from_an_unrelated_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            (p / "policy.json").write_text(json.dumps(POLICY))
            (p / "snapshot.json").write_text(json.dumps(fixture()))
            result = subprocess.run(["/bin/bash", str(ROOT / "gh-repo-checks"), "settings",
                                     "--policy", str(p / "policy.json"), "--snapshot", str(p / "snapshot.json"),
                                     "--json"], cwd=p, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), audit(fixture(), POLICY))

    def test_cli_unknown_exit_is_two_and_json_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            (p / "policy.json").write_text(json.dumps(POLICY))
            (p / "snapshot.json").write_text(json.dumps({"repo": "example/repository"}))
            result = subprocess.run(["python3", str(ROOT / "checks/settings.py"), "--policy", str(p / "policy.json"),
                                     "--snapshot", str(p / "snapshot.json"), "--json"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
