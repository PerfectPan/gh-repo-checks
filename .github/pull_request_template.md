Title format: `type(scope): summary`, in English.

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.

## Summary

<!-- What changed and why. -->

-

## Validation

<!-- Commands you ran and their results. Name skipped checks and why. -->

- [ ] Self-test under bash 3.2: `/bin/bash tests/run.sh`
- [ ] Shellcheck: `shellcheck -x gh-repo-checks checks/*.sh scripts/*.sh tests/*.sh`
- [ ] Repository checks: `./gh-repo-checks repository`

## Risks

<!-- Optional; delete this section when there are none. A change that can fail a repository that passed before needs a new major version. -->

-
