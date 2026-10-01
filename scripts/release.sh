#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/release.sh vX.Y.Z

Tags origin/main as vX.Y.Z, moves the major tag vX to the same commit, pushes
both tags, and creates the GitHub release. Run it from a clean checkout of
main after CI passed on that commit.
USAGE
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
esac

version="${1:-}"
if [[ $# -ne 1 || ! "$version" =~ ^v([0-9]+)\.[0-9]+\.[0-9]+$ ]]; then
  usage >&2
  exit 1
fi
major="v${BASH_REMATCH[1]}"

fail() {
  printf 'release: %s\n' "$*" >&2
  exit 1
}

# Moving major tags change on every release; --force updates the local copies.
git fetch --quiet --force --tags origin main
if [[ -n "$(git status --porcelain)" ]]; then
  fail "the working tree has uncommitted changes"
fi
if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]]; then
  fail "HEAD is not origin/main; check out and pull main first"
fi
if git rev-parse -q --verify "refs/tags/$version" >/dev/null; then
  fail "tag $version already exists"
fi

git tag -a "$version" -m "$version"
git tag -f "$major" "$version^{commit}"
git push origin "refs/tags/$version"
git push --force origin "refs/tags/$major"
gh release create "$version" --verify-tag --generate-notes --title "$version"

printf 'release: %s published; %s now points to it\n' "$version" "$major"
