# Contributing

## Development

```bash
# every command against fixture repositories, under the oldest supported bash
/bin/bash tests/run.sh

# lint the scripts
shellcheck -x gh-repo-checks checks/*.sh scripts/*.sh tests/*.sh

# check this repository with the code in the checkout
./gh-repo-checks repository
./gh-repo-checks pr-title "fix(pr-body): accept CRLF bodies"
./gh-repo-checks pr-body pr-body.md
```

Run `./gh-repo-checks` from the checkout to try a change; an installed extension runs the released code.

## Layout

- `gh-repo-checks`: the extension entry point. It dispatches to `checks/<command>.sh` under the same bash.
- `action.yml`: the composite action. It runs the same entry point and passes event fields through environment variables.
- `checks/`: one script per command, plus `review-sections.sh`, the single list of review sections.
- `tests/run.sh`: the self-test. It builds fixture repositories in a temporary directory.
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

Use a conventional English title, `type(scope): summary`, and fill every section of the pull request template. The `Review` workflow runs this repository's action from the pull request's own commit, and the `CI` workflow runs the self-test on Ubuntu and macOS.

## Compatibility And Releases

Downstream repositories reference the moving major tag `@v1`. A change that can fail a repository that passed before, such as a new default required file, a new scanned pattern, or a changed review section, needs a new major version; state the release impact in the pull request.

After the change lands on `main` and CI passes on both Ubuntu and macOS (bash 5 and `/bin/bash` 3.2), release with:

```bash
scripts/release.sh vX.Y.Z
```

The release is done when `git rev-parse vX` and `git rev-parse vX.Y.Z` name the same commit and `gh extension upgrade repo-checks` moves a local install to it. A new major version also needs its consumers moved: the `@vN` references in PerfectPan/project-template and PerfectPan/project-template-rush `review.yml`, each downstream repository's workflows, and rivus-agent's `gh extension install ... --pin vN`.

## Security Reports

Use `SECURITY.md`. Do not include secrets, exploit details, or private infrastructure in public issues or pull requests.
