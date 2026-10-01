Title format: `type(scope): summary`, in English.

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.

## Summary

-

## Motivation

-

## Implementation Notes

-

## Validation

- [ ] Self-test under bash 3.2: `/bin/bash tests/run.sh`
- [ ] Shellcheck: `shellcheck -x gh-repo-checks checks/*.sh scripts/*.sh tests/*.sh`
- [ ] Repository checks: `./gh-repo-checks repository`
- [ ] PR title: `./gh-repo-checks pr-title "<title>"`
- [ ] PR description: `./gh-repo-checks pr-body <body-file>`

Skipped gates and reasons:

-

## Evidence

- Linked issue or requirement:
- Test output or workflow run:
- Release impact (patch, minor, or major for downstream repositories):

## Safety Checklist

- [ ] No credentials, tokens, private hostnames, personal filesystem paths, or generated logs are included.
- [ ] Scripts still run under macOS `/bin/bash` 3.2 and Linux bash 5.
- [ ] README documents changed commands, defaults, or configuration.
- [ ] A change that can fail a previously passing repository is released as a new major version.

## Follow-up Risks

-
