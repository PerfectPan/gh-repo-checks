# gh-repo-checks

Review checks for PerfectPan repositories, shipped from one versioned source as a GitHub CLI extension and a GitHub Action, plus the shared npm release workflow for repositories that version with Changesets. Repositories reference a release instead of copying the check scripts or the release workflow.

| Command | Checks |
| --- | --- |
| `pr-title` | The PR/MR title is an English Conventional Commit: `type(scope): summary`. |
| `pr-body` | The PR/MR description has Summary and Validation sections with more than template placeholders, and no agent attribution lines. Other sections are optional. |
| `repository` | Required files exist, no local or generated artifacts are tracked, no obvious secrets, personal paths, or forbidden patterns are tracked, and the PR/MR templates contain the required review sections. |
| `protect` | Previews or applies GitHub branch protection that requires these checks. |
| `settings` | Audits GitHub settings and selected CI workflows against an explicit policy, without writing settings. |
| `release-plan` | Every pending Changesets record names only packages that `changeset version` releases. |
| `first-publish` | The public packages a release would version or publish already have a version on npm. |

The commands need bash (macOS `/bin/bash` 3.2 or newer), Git, and Perl. Installing the extension and `protect` need the [GitHub CLI](https://cli.github.com/).

## Install

### GitHub CLI extension

```bash
gh extension install PerfectPan/gh-repo-checks
gh extension upgrade repo-checks
```

`gh` installs a script extension as a Git clone of the default branch, and `gh extension upgrade` pulls the latest `main`. To stay on one release, install with `--pin v1.0.0`; a pinned extension does not upgrade until it is reinstalled.

### GitHub Action

```yaml
- uses: PerfectPan/gh-repo-checks@v1
  with:
    check: repository # or pr-title, pr-body, release-plan
```

`pr-title` and `pr-body` read the title and body from the `pull_request` event payload. Check out the repository before `repository` and `pr-body`: the repository check reads its files, and the description check treats lines copied from the repository's PR/MR template as placeholders. `release-plan` runs after the repository's dependencies are installed, because it reads the installed `@changesets/cli`.

## Commands

### `gh repo-checks pr-title TITLE`

Accepts the types `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, and `revert`, an optional lowercase scope (`a-z`, `0-9`, `.`, `_`, `-`), an optional `!`, then `: ` and a summary. CJK characters, including full-width punctuation, are rejected. Bot-generated titles follow the same rule, for example `chore(release): version packages` or `chore(deps): bump <package> to <version>`.

### `gh repo-checks pr-body [FILE|-]`

Reads FILE, or stdin when FILE is omitted or `-`, and fails when:

- a [required review section](#review-sections), Summary or Validation, is missing;
- Summary or Validation contains only blank lines, empty bullets or checkboxes, HTML comments, or lines copied unchanged from `.github/pull_request_template.md` or `.gitlab/merge_request_templates/default.md`;
- a line attributes the text to a tool, such as "Generated with <tool>".

Run it inside the repository so the template lines are found. CRLF line endings from the GitHub web editor are accepted.

### `gh repo-checks repository [--staged]`

Runs from the root of the current Git repository and stops at the first failing step:

1. Required files exist: the defaults below, adjusted by [configuration](#configuration).
2. No local or generated artifacts are tracked: `node_modules`, `dist`, `build`, `coverage`, `tmp`, `temp`, tool caches, `.DS_Store`, `.env` files, `*.log`, `.omx`, `.codex`, or `.claude/settings.local.json`.
3. Tracked text files contain no obvious secrets (AWS access keys, GitHub and Slack tokens, private keys), personal home directory paths, the private placeholders used by the project template, or `forbid` patterns.
4. `.github/pull_request_template.md` and, when present, `.gitlab/merge_request_templates/default.md` contain the required review sections, Summary and Validation, as `## ` headings.

`--staged` checks the Git index instead of the working tree, including the configuration file, so a pre-commit hook judges exactly what is about to be committed.

Default required files:

- `AGENTS.md`, `CONTRIBUTING.md`, `README.md`, `SECURITY.md`, `LICENSE`
- `docs/README.md`, `docs/specs/0000-template.md`, `docs/plans/0000-template.md`
- `.editorconfig`, `.gitignore`
- `.github/pull_request_template.md`
- `.github/workflows/ci.yml` or `.github/workflows/ci.yml.example`
- `.gitlab/merge_request_templates/default.md`, only when `.gitlab/` exists

### `gh repo-checks protect`

```bash
gh repo-checks protect [--repo OWNER/REPO] [--branch BRANCH] [--approvals N] [--check NAME]... [--no-review-checks] [--apply]
```

Prints the branch protection payload; `--apply` sends it with `gh api` and needs an account that can edit repository settings. The payload requires pull requests with N approving reviews (default 1, dismissed by new pushes), linear history, resolved conversations, enforcement for admins, and the status checks `repository checks`, `conventional PR title`, and `PR description`, plus each `--check`, such as the CI job names.

`--no-review-checks` drops the three built-in status checks, so only the `--check` names are required; it fails without at least one `--check`. Use it when the repository's Review workflow does not run on every pull request, for example when it runs only on `workflow_dispatch` and reports through another status check.

`--repo` defaults to the current repository and `--branch` to its default branch. A repository with a single maintainer cannot approve its own pull requests; pass `--approvals 0` to keep the other protections. If the repository uses rulesets, add the checks to the ruleset instead of layering classic branch protection on top.

### `gh repo-checks settings`

```bash
gh repo-checks settings --repo OWNER/REPO --policy policy.json --json
# Saved connector evidence can be audited without making API requests:
gh repo-checks settings --snapshot snapshot.json --policy policy.json --json
```

The entry point is thin; policy validation, GitHub reads, branch rules, bypass
scope, workflow parsing, report assembly, and CLI handling live in separate
modules under `checks/settings_audit/`. Tests are grouped by the same boundaries.

This additive command is read-only and separate from `protect`. It only calls
`gh api --hostname github.com --method GET`, does not install tools or create
credentials, and never changes GitHub configuration. It requires Python 3;
PyYAML is optional for workflow parsing. Missing tools or unreadable endpoints
produce `unknown` findings rather than silently succeeding. Workflow YAML with
duplicate mapping keys is rejected as `parse: unknown`, rather than accepting
the last value and reporting misleading findings.

The required JSON policy contains `version: 1` and optional `repository`,
`branch`, `private_ci`, and repository-keyed `overrides` objects. Unknown fields
and invalid types are errors; policy data is never executed. Example:

```json
{
  "version": 1,
  "repository": {
    "allow_merge_commit": false,
    "allow_squash_merge": true,
    "allow_rebase_merge": true,
    "delete_branch_on_merge": true,
    "allow_auto_merge": false
  },
  "branch": {
    "strict": false,
    "require_pull_request": true,
    "required_approvals": 0,
    "require_code_owner_reviews": false,
    "require_last_push_approval": false,
    "require_conversation_resolution": true,
    "require_linear_history": true,
    "allow_force_pushes": false,
    "allow_deletions": false,
    "enforce_admins": true,
    "required_checks": null
  },
  "private_ci": {
    "workflows": null,
    "required_pr_events": ["opened", "synchronize", "ready_for_review"],
    "skip_draft": true,
    "no_default_branch_push": true
  }
}
```

Use the repository's actual required context names for `required_checks` and
explicit CI file paths for `workflows`; `null` stays unknown. The auditor does
not guess CI names from filenames or workflow names. Repository overrides
merge individual section fields. `decision_required` holds unresolved decision
messages, and `pending_fields` holds branch fields such as
`branch.require_pull_request` that must remain unknown until a policy exception
is decided. These markers do not authorize any mutation.

`ruleset_bypasses` optionally maps a rule type (`pull_request`,
`required_status_checks`, `deletion`, `non_fast_forward`, or
`required_linear_history`) to an exact list of approved User actors. Each actor
has `actor_type: "User"`, a numeric `actor_id`, and explicit `bypass_mode`
(`always` or `pull_request`). An empty list prohibits bypass; null is undecided.
Role-based substitutions are rejected. The auditor checks every rule in the
entire active ruleset before accepting an exception, so a PR exception cannot
silently cover deletion or force-push restrictions. It also reports classic PR and CI
protection overlap as unknown rather than claiming direct pushes will work.
A ruleset PR bypass covers all of that PR rule's parameters, including
conversation resolution; separate enforcement needs separate evidence.


Classic protection and all pages of active effective rules are read. A
403/404 does not prove protection is absent. Hidden ruleset bypass actors and
actor-specific exceptions remain unknown. Admin enforcement is a conservative
source-configuration comparison, not proof of a particular user's effective
permissions. Required checks compare the exact union of context names, not
app bindings or actual run results. Stronger overlapping rules can produce a
configuration drift finding even if another rule already provides protection;
review the overlap instead of automatically changing either rule.

For private CI, the command checks declared PR events, a small set of proven
job-level Draft guards, and default-branch push triggers. Complex conditions,
filters, or globs stay unknown. Job guards can still create a skipped workflow
record; they prevent job execution. Runtime execution always has a separate
unknown finding until actual jobs at the exact commit are verified outside this
static auditor. The command never dispatches a workflow.

Exit status is `0` for all evaluated comparisons passing, `1` for known drift,
and `2` for unknown-only or invalid input. A drift report may also contain
unknown findings; always inspect the complete JSON. An empty policy does not
pass vacuously.

Snapshot JSON has `repo`, `branch`, `metadata`, `classic`, `rules`, `rulesets`,
and `workflows`. API responses use `{"state":"ok","data":...}` or
`{"state":"unknown","reason":"..."}`. `rules.data` is the complete effective
rules array; `rulesets` maps IDs to response envelopes; each workflow has
`path`, `state`, and UTF-8 `text`. Do not fabricate successful empty responses
from failed reads. Save timestamps and source links alongside snapshots, and
keep private repository reports private.

### `gh repo-checks release-plan`

Reads the pending `.changeset/*.md` records with the libraries of the repository's installed `@changesets/cli` 3.x and fails when a record names a package that `changeset version` skips: a private package (unless `privatePackages.version` is set) or an ignored one, including `none` records. `changeset version` leaves such a record pending, so the release flow keeps preparing a version pull request and never publishes. A record that Changesets refuses outright, such as one naming a private package beside a public one, fails with Changesets' own message. Needs Node.js and the installed dependencies; run it from the repository root.

### `gh repo-checks first-publish [version|publish]`

npm Trusted Publishing cannot create a package name, so a release of a name that has never been published fails at the token exchange. This command asks the registry (`npm view <name> versions`) for each public, non-ignored package and fails when one has no version yet:

- `version` (the default) checks only the packages the pending records release, so an unrelated new package does not block an existing package's version pull request.
- `publish` checks every public, non-ignored package.

A registry failure other than a 404 fails with its own message instead of reporting the name as missing. `RELEASE_REGISTRY` overrides the registry, which defaults to `https://registry.npmjs.org/`. Needs Node.js, npm and the installed `@changesets/cli` 3.x.

## Configuration

`.github/repo-checks.conf` adjusts the `repository` check; without the file the defaults apply. The file has one directive per line. Blank lines and lines starting with `#` are ignored, and everything after the directive word is the value, so trailing comments are not supported.

| Directive | Value | Effect |
| --- | --- | --- |
| `require` | A path, or alternatives separated by `\|` | Adds a required file. |
| `unrequire` | A path from the default list | Drops the default requirement that lists this path. A path that is not a default is an error. |
| `forbid` | An extended regular expression | Fails the scan when a tracked text file matches. |
| `exclude` | A Git pathspec: a file, a directory, or a glob | Skips matching files in the secret, path, and `forbid` scan. |

Unknown directives and invalid `forbid` patterns fail the check instead of being ignored. The scan always skips `AGENTS.md`, `CONTRIBUTING.md`, and `SECURITY.md`, which document the scanned patterns, and the configuration file itself.

The configuration is data and never runs commands, so checking an untrusted checkout does not execute its code. Run repository-specific checks as separate workflow steps and hook commands, as shown below.

Example:

```conf
# Release tooling this repository depends on.
require .node-version
require .github/dependabot.yml|.github/renovate.json

# Specs live at the repository root in this monorepo.
unrequire docs/specs/0000-template.md
require specs/0000-template.md

# Packages publish only to the public registry.
forbid registry\.corp\.example

# Fixtures contain fake credentials on purpose.
exclude tests/fixtures
```

## Use in a repository

### Review workflow

Add `.github/workflows/review.yml`. Keep the job names: branch protection requires the status checks `repository checks`, `conventional PR title`, and `PR description`.

```yaml
name: Review

on:
  pull_request:
    types: [opened, edited, reopened, synchronize, ready_for_review]
  push:
    branches: [main]

jobs:
  repository-checks:
    name: repository checks
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: PerfectPan/gh-repo-checks@v1
        with:
          check: repository

  pr-title:
    name: conventional PR title
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: PerfectPan/gh-repo-checks@v1
        with:
          check: pr-title

  pr-body:
    name: PR description
    # Bot PRs (dependency updates, release PRs) do not use the template; their titles are still checked.
    if: github.event_name == 'pull_request' && github.event.pull_request.user.type != 'Bot'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: PerfectPan/gh-repo-checks@v1
        with:
          check: pr-body
```

The `edited` event type re-runs the checks when the title or description changes. A skipped `PR description` job on a bot PR still satisfies the required status check. Add repository-specific checks as further steps of the `repository checks` job:

```yaml
      - uses: PerfectPan/gh-repo-checks@v1
        with:
          check: repository
      - run: node scripts/check-documentation.mjs
```

### npm releases

A repository that versions with Changesets and publishes to npm calls the shared workflow from a workflow file of its own, which npm Trusted Publishing is bound to:

```yaml
jobs:
  release:
    uses: PerfectPan/gh-repo-checks/.github/workflows/npm-release.yml@v1
    permissions:
      contents: write
      pull-requests: write
      id-token: write
```

[docs/npm-release.md](docs/npm-release.md) is the release runbook: the complete caller workflow, the inputs, what each repository keeps, one-time npm setup, cutting a release and failure recovery. Add the `release-plan` check to CI after the dependency install:

```yaml
      - uses: PerfectPan/gh-repo-checks@v1
        with:
          check: release-plan
```

### Pre-commit hook

Add `.githooks/pre-commit` and enable it with `git config core.hooksPath .githooks`:

```bash
#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

git diff --cached --check

# CI runs the same check and is authoritative, so a checkout without the
# extension warns instead of blocking the commit.
if gh repo-checks --help >/dev/null 2>&1; then
  gh repo-checks repository --staged
else
  printf 'pre-commit: gh repo-checks is not installed; skipping repository checks\n' >&2
  printf 'pre-commit: install it with: gh extension install PerfectPan/gh-repo-checks\n' >&2
fi
```

Append repository-specific commands after the repository check.

## Review sections

Two `## ` headings are required, defined once in [`checks/review-sections.sh`](checks/review-sections.sh):

- `Summary`: what changed and why.
- `Validation`: how the change was tested.

Every PR/MR template must contain both headings, and every description must fill both with more than template placeholders. Any other section is optional: a description may keep, delete, or add sections without failing the check.

Recommended `.github/pull_request_template.md` (keep `.gitlab/merge_request_templates/default.md` identical when the repository uses GitLab):

```markdown
Title format: `type(scope): summary`, in English.

## Summary

<!-- What changed and why. Link the issue, Spec, or Plan when there is one. -->

-

## Validation

<!-- Commands you ran and their results. Name skipped checks and why. -->

-

## Risks

<!-- Optional: compatibility, rollout, or follow-up risks. Delete this section when there are none. -->

-
```

Lines copied unchanged from the template, empty bullets and checkboxes, and single-line HTML comments count as placeholders, so a template's own checklist items count only after they are edited or checked.

## Versioning

Releases are tagged `vX.Y.Z`, and the major tag `vX` moves to the newest `vX.Y.Z`. Workflows reference the major tag, `PerfectPan/gh-repo-checks@v1`, not a commit SHA, so they receive fixes and compatible additions without edits. A change that can fail a repository that passed before, such as a new default required file, a new scanned pattern, or a new required review section, ships under a new major tag.

To cut a release after CI passes on `main`:

```bash
scripts/release.sh v1.2.3
```

The script tags `origin/main` as `v1.2.3`, force-moves `v1` to the same commit, pushes both tags, and creates the GitHub release with generated notes.

## Development

```bash
/bin/bash tests/run.sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
CHANGESETS_CLI_ROOT=... node --test tests/release.test.mjs
shellcheck -x gh-repo-checks checks/*.sh scripts/*.sh tests/*.sh
./gh-repo-checks repository
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the layout and the shell compatibility rules.

## License

MIT. See [LICENSE](LICENSE).
