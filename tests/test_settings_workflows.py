"""Offline regression tests; no GitHub access or writes."""

import unittest

# Shared fixtures establish the checkout's checks package on the test path.
import settings_fixtures
from settings_audit.workflows import audit_workflow


class WorkflowTest(unittest.TestCase):
    def inspect(self, text, **overrides):
        found = []
        policy = {"required_pr_events": ["opened", "synchronize", "ready_for_review"],
                  "skip_draft": True, "no_default_branch_push": True}
        policy.update(overrides)
        audit_workflow("ci.yml", text, policy,
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

    def test_duplicate_top_level_keys_are_unknown(self):
        text = self.workflow().replace("on:\n", "on: push\non:\n")
        self.assertEqual(self.inspect(text), {"parse": "unknown"})

    def test_duplicate_event_types_are_unknown(self):
        events = "pull_request:\n    types: [opened]\n    types: [opened, synchronize, ready_for_review]"
        self.assertEqual(self.inspect(self.workflow(events)), {"parse": "unknown"})

    def test_duplicate_job_guards_are_unknown(self):
        guard = "if: true\n    if: ${{ !github.event.pull_request.draft }}"
        self.assertEqual(self.inspect(self.workflow(guard=guard)), {"parse": "unknown"})

    def test_duplicate_step_keys_are_unknown(self):
        text = self.workflow().replace("steps: []", "steps:\n      - run: echo first\n        run: echo second")
        self.assertEqual(self.inspect(text), {"parse": "unknown"})

    def test_duplicate_quoted_and_plain_keys_are_unknown(self):
        text = self.workflow().replace("on:\n", "'on': push\non:\n")
        self.assertEqual(self.inspect(text), {"parse": "unknown"})

    def test_same_key_in_distinct_mappings_is_valid(self):
        text = self.workflow().replace("steps: []", "steps:\n      - run: echo first\n      - run: echo second")
        result = self.inspect(text)
        self.assertEqual(result.pop("execution"), "unknown")
        self.assertEqual(set(result.values()), {"pass"})

    def test_malformed_yaml_is_unknown(self):
        self.assertEqual(self.inspect("on: ["), {"parse": "unknown"})


if __name__ == "__main__":
    unittest.main()
