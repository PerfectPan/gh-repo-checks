# gh-repo-checks

Review checks for PerfectPan repositories, shipped from one versioned source as a GitHub CLI extension and a GitHub Action. Repositories reference a release instead of copying the check scripts.

| Command | Checks |
| --- | --- |
| `pr-title` | The PR/MR title is an English Conventional Commit: `type(scope): summary`. |
| `pr-body` | The PR/MR description keeps every review section, fills Summary and Validation beyond template placeholders, and has no agent attribution lines. |
| `repository` | Required files exist, no local or generated artifacts are tracked, no obvious secrets, personal paths, or forbidden patterns are tracked, and the PR/MR templates keep every review section. |
| `protect` | Previews or applies GitHub branch protection that requires these checks. |

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
    check: repository # or pr-title, pr-body
```

`pr-title` and `pr-body` read the title and body from the `pull_request` event payload. Check out the repository before `repository` and `pr-body`: the repository check reads its files, and the description check treats lines copied from the repository's PR/MR template as placeholders.

## Commands

### `gh repo-checks pr-title TITLE`

Accepts the types `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, and `revert`, an optional lowercase scope (`a-z`, `0-9`, `.`, `_`, `-`), an optional `!`, then `: ` and a summary. CJK characters, including full-width punctuation, are rejected. Bot-generated titles follow the same rule, for example `chore(release): version packages` or `chore(deps): bump <package> to <version>`.

### `gh repo-checks pr-body [FILE|-]`

Reads FILE, or stdin when FILE is omitted or `-`, and fails when:

- a [review section](#review-sections) heading is missing;
- Summary or Validation contains only blank lines, empty bullets or checkboxes, HTML comments, or lines copied unchanged from `.github/pull_request_template.md` or `.gitlab/merge_request_templates/default.md`;
- a line attributes the text to a tool, such as "Generated with <tool>".

Run it inside the repository so the template lines are found. CRLF line endings from the GitHub web editor are accepted.

### `gh repo-checks repository [--staged]`

Runs from the root of the current Git repository and stops at the first failing step:

1. Required files exist: the defaults below, adjusted by [configuration](#configuration).
2. No local or generated artifacts are tracked: `node_modules`, `dist`, `build`, `coverage`, `tmp`, `temp`, tool caches, `.DS_Store`, `.env` files, `*.log`, `.omx`, `.codex`, or `.claude/settings.local.json`.
3. Tracked text files contain no obvious secrets (AWS access keys, GitHub and Slack tokens, private keys), personal home directory paths, the private placeholders used by the project template, or `forbid` patterns.
4. `.github/pull_request_template.md` and, when present, `.gitlab/merge_request_templates/default.md` contain every review section as a `## ` heading.

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
gh repo-checks protect [--repo OWNER/REPO] [--branch BRANCH] [--approvals N] [--check NAME]... [--apply]
```

Prints the branch protection payload; `--apply` sends it with `gh api` and needs an account that can edit repository settings. The payload requires pull requests with N approving reviews (default 1, dismissed by new pushes), linear history, resolved conversations, enforcement for admins, and the status checks `repository checks`, `conventional PR title`, and `PR description`, plus each `--check`, such as the CI job names.

`--repo` defaults to the current repository and `--branch` to its default branch. A repository with a single maintainer cannot approve its own pull requests; pass `--approvals 0` to keep the other protections. If the repository uses rulesets, add the checks to the ruleset instead of layering classic branch protection on top.

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

Every PR/MR template and description must contain these `## ` headings, defined once in [`checks/review-sections.sh`](checks/review-sections.sh):

- Summary
- Motivation
- Implementation Notes
- Validation
- Evidence
- Safety Checklist
- Follow-up Risks

## Versioning

Releases are tagged `vX.Y.Z`, and the major tag `vX` moves to the newest `vX.Y.Z`. Workflows reference the major tag, `PerfectPan/gh-repo-checks@v1`, not a commit SHA, so they receive fixes and compatible additions without edits. A change that can fail a repository that passed before, such as a new default required file, a new scanned pattern, or a changed review section, ships under a new major tag.

To cut a release after CI passes on `main`:

```bash
scripts/release.sh v1.2.3
```

The script tags `origin/main` as `v1.2.3`, force-moves `v1` to the same commit, pushes both tags, and creates the GitHub release with generated notes.

## Development

```bash
/bin/bash tests/run.sh
shellcheck -x gh-repo-checks checks/*.sh scripts/*.sh tests/*.sh
./gh-repo-checks repository
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the layout and the shell compatibility rules.

## License

MIT. See [LICENSE](LICENSE).
