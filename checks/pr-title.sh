#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  -h|--help)
    cat <<'USAGE'
Usage:
  gh repo-checks pr-title TITLE

Checks that a PR or MR title is an English Conventional Commit:
type(scope): summary
USAGE
    exit 0
    ;;
esac

title="${1:-}"
allowed_types="feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert"
pattern="^(${allowed_types})(\\([a-z0-9._-]+\\))?!?: [^[:space:]].*"

if [[ -z "${title//[[:space:]]/}" ]]; then
  printf 'repo-checks pr-title: missing PR title\n' >&2
  exit 1
fi

if [[ ! "$title" =~ $pattern ]]; then
  printf 'repo-checks pr-title: title must match type(scope): summary\n' >&2
  printf 'repo-checks pr-title: allowed types: %s\n' "$allowed_types" >&2
  printf 'repo-checks pr-title: got: %s\n' "$title" >&2
  exit 1
fi

# Titles are English Conventional Commits. Perl is used because Bash regex
# character classes depend on the runner locale.
if printf '%s' "$title" | perl -CI -0777 -ne 'exit(/[\p{Han}\p{Hiragana}\p{Katakana}\p{Hangul}\x{3000}-\x{303F}\x{FF00}-\x{FFEF}]/ ? 0 : 1)'; then
  printf 'repo-checks pr-title: title must be English; CJK characters are not allowed\n' >&2
  printf 'repo-checks pr-title: got: %s\n' "$title" >&2
  exit 1
fi

printf 'repo-checks pr-title: ok\n'
