# Contributing

## Development

```bash
# every command against fixture repositories, under the oldest supported bash
/bin/bash tests/run.sh

# settings audit tests (PyYAML enables workflow parsing tests)
python3 -m unittest discover -s tests -p 'test_*.py' -v

# release-plan and first-publish tests, against an installed @changesets/cli 3.x
cli_root="$(mktemp -d)" && npm install --prefix "$cli_root" --no-audit --no-fund @changesets/cli@3
CHANGESETS_CLI_ROOT="$cli_root" node --test tests/release.test.mjs

# lint the shared release workflow; actionlint 1.7.12 does not know the job.workflow_* context yet
actionlint -ignore 'property "workflow_(repository|sha)" is not defined' .github/workflows/*.yml

# lint the scripts
shellcheck -x gh-repo-checks checks/*.sh scripts/*.sh tests/*.sh

# check this repository with the code in the checkout
./gh-repo-checks repository
./gh-repo-checks pr-title "fix(pr-body): accept CRLF bodies"
./gh-repo-checks pr-body pr-body.md
```

Run `./gh-repo-checks` from the checkout to try a change; an installed extension runs the released code.

## Layout

- `gh-repo-checks`: the extension entry point. It dispatches to `checks/<command>.sh` under the same bash. The additive `settings` command dispatches to Python 3, and `release-plan` and `first-publish` dispatch to Node.js, because they read the repository's installed `@changesets/cli`.
- `action.yml`: the composite action. It runs the same entry point and passes event fields through environment variables.
- `checks/`: one script per command, plus `review-sections.sh`, the single list of required review sections.
- `checks/release-plan.mjs` and `checks/first-publish.mjs`: thin entry points for the Changesets checks. `checks/release/changesets.mjs` loads the Changesets libraries through the repository's `@changesets/cli` and assembles the release plan; `checks/release/plan-rules.mjs` holds the release-plan rules and reads `allow-major` from `.github/repo-checks.conf`; `checks/release/registry.mjs` owns the `npm view` lookup.
- `.github/workflows/npm-release.yml`: the shared npm release workflow (`workflow_call`). It checks out this repository at its own commit (`job.workflow_sha`) to run the Changesets checks, so a caller pinned to a release runs that release's checks. `docs/npm-release.md` is its runbook.
- `checks/settings.py`: thin entry point for the read-only settings audit.
- `checks/settings_audit/`: `policy.py` validates policy data; `github.py` owns GET-only collection; `branches.py` compares protections; `bypasses.py` checks exact actor scope; `workflow_yaml.py` rejects duplicate mapping keys without coercing YAML scalars; `workflows.py` handles conservative workflow checks; `audit.py` assembles reports; `cli.py` owns arguments and output. Keep the collection path separate from write commands.
- `tests/test_settings.py`, `tests/test_settings_bypasses.py`, and `tests/test_settings_workflows.py`: offline core/CLI, bypass, and workflow regression tests, with shared data in `tests/settings_fixtures.py`.
- `tests/run.sh`: the self-test. It builds fixture repositories in a temporary directory.
- `tests/release.test.mjs`: the Changesets check tests. They run the dispatcher against generated workspaces linked to the CLI in `CHANGESETS_CLI_ROOT` and a local HTTP registry.
- `scripts/release.sh`: tags and publishes a release.
- `.github/repo-checks.conf`: this repository's own configuration for the repository check.

## Shell Compatibility

The scripts run under macOS `/bin/bash` 3.2 and Linux bash 5, and CI runs the self-test with `/bin/bash` on both. Bash 3.2 differs in ways that pass silently on a newer shell:

- Under `set -u`, expanding an empty array as `"${list[@]}"` fails. Use `${list[@]+"${list[@]}"}` or check the length first.
- Pattern substitution such as `${text//[[:space:]]/}` or `${text//$'\r'/}` is slow enough on a long PR body to time out a check. Test emptiness with `[[ ! "$text" =~ [^[:space:]] ]]` and delete characters with `tr`.
- `grep -q` at the end of a pipeline can exit before the writer finishes, which fails the pipeline under `pipefail`. Send `grep` output to `/dev/null` instead.
- Bash character classes depend on the locale. Use Perl for Unicode checks.
- Associative arrays, `mapfile`, `${var,,}`, and `source <(...)` are unavailable.

## Pull Requests

Use a conventional English title, `type(scope): summary`, and fill the Summary and Validation sections of the pull request template. The `Review` workflow runs this repository's action from the pull request's own commit, and the `CI` workflow runs the self-test on Ubuntu and macOS, the release check tests against the newest `@changesets/cli` 3.x (also weekly), shellcheck and actionlint.

## Compatibility And Releases

Downstream repositories reference the moving major tag `@v1`. A change that can fail a repository that passed before, such as a new default required file, a new scanned pattern, or a new required review section, needs a new major version; state the release impact in the pull request. The release workflow follows the same rule: a new required input, a removed input or output, or a stricter default needs a new major version. One exception: a new `release-plan` rule that judges only the pending release (change records, `fixed` and `linked` groups, `allow-major`) may ship in a minor version when every repository that runs the check, directly or through `npm-release.yml`, passes it on its default branch at the time `scripts/release.sh` moves the major tag. Such a repository fails only after a later change of its own. The pull request lists each of those repositories with its result and names the jobs the rule affects. Every `@v1` caller picks up a workflow change on its next release, so state in the pull request which job it affects.

After the change lands on `main` and CI passes on both Ubuntu and macOS (bash 5 and `/bin/bash` 3.2), release with:

```bash
scripts/release.sh vX.Y.Z
```

The release is done when `git rev-parse "vX^{commit}" "vX.Y.Z^{commit}"` prints the same commit twice (plain `git rev-parse vX.Y.Z` prints the annotated tag object, not the commit) and `gh extension upgrade repo-checks` moves a local install to it. A new major version also needs its consumers moved: the `@vN` references in PerfectPan/project-template and PerfectPan/project-template-rush `review.yml`, each downstream repository's workflows, and rivus-agent's `gh extension install ... --pin vN`.

## Security Reports

Use `SECURITY.md`. Do not include secrets, exploit details, or private infrastructure in public issues or pull requests.
