"""Offline regression tests; no GitHub access or writes."""

import copy
import unittest

from settings_fixtures import fixture, ok
from settings_audit.audit import audit
from settings_audit.policy import validate_policy


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
        return next(f for f in audit(self.snapshot, self.policy)["findings"] if f["check"] == key)

    def test_exact_owner_pr_and_ci_bypasses_pass_when_split_from_protection(self):
        self.assertEqual(audit(self.snapshot, self.policy)["status"], "pass")

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
        self.assertEqual(audit(self.snapshot, self.policy)["status"], "unknown")

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
            validate_policy(self.policy)


if __name__ == "__main__":
    unittest.main()
