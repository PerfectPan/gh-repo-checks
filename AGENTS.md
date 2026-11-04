# Agent Guidelines

This repository is the single source of the review checks that PerfectPan repositories run through `PerfectPan/gh-repo-checks@v1` and the `gh repo-checks` extension. Every change reaches those repositories, so keep changes scoped and behavior documented.

- Read `README.md` for current behavior and `CONTRIBUTING.md` for the layout, shell compatibility rules, and release policy.
- Keep command entry points thin. Split independent responsibilities into focused files instead of putting policy, transport, rules, parsing, and output in one large script. Choose boundaries by responsibility rather than a fixed line limit.
- Apply this structure to both Shell and Python. Preserve macOS Bash 3.2 compatibility for existing shell checks; assess runtime, dependency, and release costs when introducing or changing languages, without making one language mandatory or forbidden.
- Group tests by the behavior they cover and share small fixtures. Refactors must preserve CLI behavior and existing test coverage.
- Do not commit credentials, private hostnames, personal filesystem paths, or generated output. Test fixtures that need such strings build them at runtime, as `tests/run.sh` does.
- Update `README.md` in the same change when a command, default, or configuration directive changes.
- PR titles and descriptions must pass this repository's own checks. Do not add agent attribution lines.
- Cut releases with `scripts/release.sh` only when the maintainer asks for a release.

Run before claiming a change is complete:

```bash
/bin/bash tests/run.sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
shellcheck -x gh-repo-checks checks/*.sh scripts/*.sh tests/*.sh
./gh-repo-checks repository
```
