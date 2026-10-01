#!/usr/bin/env bash
set -euo pipefail

config=".github/repo-checks.conf"
staged=false

usage() {
  cat <<'USAGE'
Usage:
  gh repo-checks repository [--staged]

Checks required repository files, tracked local artifacts, obvious secrets,
private paths, forbidden patterns, and required review sections. Settings for
the repository are read from .github/repo-checks.conf when it exists.

Options:
  --staged  Check the Git index instead of the working tree. Use this from
            pre-commit hooks.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --staged)
      staged=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'repo-checks repository: unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=checks/review-sections.sh
source "$script_dir/review-sections.sh"

fail() {
  printf 'repo-checks repository: %s\n' "$*" >&2
  exit 1
}

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "not inside a Git repository"
cd "$repo_root"

file_present() {
  if [[ "$staged" == true ]]; then
    git cat-file -e ":$1" 2>/dev/null
  else
    [[ -f "$1" ]]
  fi
}

read_file() {
  if [[ "$staged" == true ]]; then
    git show ":$1"
  else
    cat "$1"
  fi
}

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

default_required_files=(
  "AGENTS.md"
  "CONTRIBUTING.md"
  "README.md"
  "SECURITY.md"
  "LICENSE"
  "docs/README.md"
  ".editorconfig"
  ".gitignore"
  ".github/pull_request_template.md"
  # Alternatives separated by "|": a project replaces the example with its real CI.
  ".github/workflows/ci.yml|.github/workflows/ci.yml.example"
  "docs/specs/0000-template.md"
  "docs/plans/0000-template.md"
)

uses_gitlab=false
if [[ "$staged" == true ]]; then
  if [[ -n "$(git ls-files -- .gitlab)" ]]; then
    uses_gitlab=true
  fi
elif [[ -d .gitlab ]]; then
  uses_gitlab=true
fi
if [[ "$uses_gitlab" == true ]]; then
  default_required_files+=(".gitlab/merge_request_templates/default.md")
fi

is_default_requirement() {
  local entry
  for entry in "${default_required_files[@]}"; do
    if [[ "|$entry|" == *"|$1|"* ]]; then
      return 0
    fi
  done
  return 1
}

extra_required_files=()
unrequired_files=()
forbidden_patterns=()
# The default excludes document the scanned patterns; the config file holds the
# repository's own forbidden patterns.
scan_excludes=(
  ":(exclude)AGENTS.md"
  ":(exclude)CONTRIBUTING.md"
  ":(exclude)SECURITY.md"
  ":(exclude)$config"
)

# The config is data only. Repository-specific scripts run as separate steps so
# that checking an untrusted checkout never executes its code.
if file_present "$config"; then
  line_number=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line_number=$((line_number + 1))
    line="$(trim "$line")"
    if [[ -z "$line" || "$line" == \#* ]]; then
      continue
    fi
    directive="${line%%[[:space:]]*}"
    value="$(trim "${line:${#directive}}")"
    if [[ -z "$value" ]]; then
      fail "$config:$line_number: missing value for $directive"
    fi
    case "$directive" in
      require)
        extra_required_files+=("$value")
        ;;
      unrequire)
        if ! is_default_requirement "$value"; then
          fail "$config:$line_number: not a default requirement: $value"
        fi
        unrequired_files+=("$value")
        ;;
      forbid)
        forbidden_patterns+=("$value")
        ;;
      exclude)
        scan_excludes+=(":(exclude)$value")
        ;;
      *)
        fail "$config:$line_number: unknown directive: $directive"
        ;;
    esac
  done < <(read_file "$config")
fi

required_files=()
for entry in "${default_required_files[@]}"; do
  keep=true
  for removed in ${unrequired_files[@]+"${unrequired_files[@]}"}; do
    if [[ "|$entry|" == *"|$removed|"* ]]; then
      keep=false
    fi
  done
  if [[ "$keep" == true ]]; then
    required_files+=("$entry")
  fi
done
if (( ${#extra_required_files[@]} > 0 )); then
  required_files+=("${extra_required_files[@]}")
fi

missing=()
for entry in ${required_files[@]+"${required_files[@]}"}; do
  found=false
  IFS='|' read -r -a alternatives <<<"$entry"
  for file in "${alternatives[@]}"; do
    if file_present "$file"; then
      found=true
      break
    fi
  done
  if [[ "$found" == false ]]; then
    missing+=("${entry//|/ or }")
  fi
done

if (( ${#missing[@]} > 0 )); then
  printf 'Missing required files:\n' >&2
  printf '  - %s\n' "${missing[@]}" >&2
  exit 1
fi

tracked_artifact_pattern='(^|/)(node_modules|dist|build|coverage|tmp|temp|\.cache|\.turbo|\.next|\.vite|\.pytest_cache|__pycache__|\.DS_Store)(/|$)|(^|/)\.env($|\.)|\.log$|(^|/)\.omx(/|$)|(^|/)\.codex(/|$)|(^|/)\.claude/settings\.local\.json$'
if [[ "$staged" == true ]]; then
  tracked_artifacts="$(git diff --cached --name-only --diff-filter=ACMR | grep -E "$tracked_artifact_pattern" || true)"
else
  tracked_artifacts="$(git ls-files | grep -E "$tracked_artifact_pattern" || true)"
fi
if [[ -n "$tracked_artifacts" ]]; then
  printf 'Tracked local, generated, or machine-specific artifacts found:\n%s\n' "$tracked_artifacts" >&2
  exit 1
fi

secret_pattern='AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9_]{36,}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN ([A-Z]+ )?PRIVATE KEY-----'
private_path_pattern='(^|[[:space:]`"'"'"'(<>=])(/Users/[^[:space:]`"'"'"'<>]+|/home/[^[:space:]`"'"'"'<>]+|C:\\Users\\)'
placeholder_pattern='private-token|internal-domain\.example|HOME_PATH_PLACEHOLDER'
findings_file="$(mktemp "${TMPDIR:-/tmp}/repo-checks-findings.XXXXXX")"
trap 'rm -f "$findings_file"' EXIT

grep_args=(-n -I -E -e "$secret_pattern" -e "$private_path_pattern" -e "$placeholder_pattern")
for pattern in ${forbidden_patterns[@]+"${forbidden_patterns[@]}"}; do
  grep_args+=(-e "$pattern")
done
if [[ "$staged" == true ]]; then
  grep_args=(--cached "${grep_args[@]}")
fi

# git grep exits 1 when nothing matches; anything above 1 is an error such as
# an invalid forbid pattern, which must not pass silently.
scan_status=0
git grep "${grep_args[@]}" -- . "${scan_excludes[@]}" >"$findings_file" 2>&1 || scan_status=$?
case "$scan_status" in
  0)
    printf 'Potential secret, private path, or forbidden pattern found:\n' >&2
    cat "$findings_file" >&2
    exit 1
    ;;
  1)
    ;;
  *)
    cat "$findings_file" >&2
    fail "git grep failed; check the forbid and exclude lines in $config"
    ;;
esac

for template in ".github/pull_request_template.md" ".gitlab/merge_request_templates/default.md"; do
  if ! file_present "$template"; then
    continue
  fi
  template_content="$(read_file "$template")"
  for section in "${required_review_sections[@]}"; do
    if ! grep -E "^## ${section}$" <<<"$template_content" >/dev/null; then
      fail "$template is missing required section: $section"
    fi
  done
done

if [[ "$staged" == true ]]; then
  printf 'repo-checks repository: ok (staged)\n'
else
  printf 'repo-checks repository: ok\n'
fi
