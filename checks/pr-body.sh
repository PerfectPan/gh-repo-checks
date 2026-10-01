#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  gh repo-checks pr-body [FILE]
  printf '%s\n' "$PR_BODY" | gh repo-checks pr-body

Checks a PR or MR description read from FILE, or from stdin when FILE is
omitted or "-". The Summary and Validation sections must be present and
contain more than template placeholders; other sections are optional. Agent
attribution lines are rejected.

Run it inside the repository: lines copied unchanged from its
.github/pull_request_template.md or .gitlab/merge_request_templates/default.md
count as placeholders.
USAGE
}

if [[ $# -gt 1 ]]; then
  usage >&2
  exit 1
fi

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
esac

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
# shellcheck source=checks/review-sections.sh
source "$script_dir/review-sections.sh"

# Descriptions edited in the GitHub web UI arrive with CRLF line endings. tr
# strips them because ${body//$'\r'/} takes seconds on a long body under macOS
# /bin/bash 3.2.
input="${1:--}"
if [[ "$input" == "-" ]]; then
  body="$(tr -d '\r')"
elif [[ -f "$input" ]]; then
  body="$(tr -d '\r' <"$input")"
else
  printf 'repo-checks pr-body: file not found: %s\n' "$input" >&2
  exit 1
fi

# A regex test instead of ${body//[[:space:]]/}: that expansion takes minutes on
# a long body under macOS /bin/bash 3.2.
if [[ ! "$body" =~ [^[:space:]] ]]; then
  printf 'repo-checks pr-body: missing PR body\n' >&2
  exit 1
fi

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

# Lines copied unchanged from a review template count as placeholders.
template_lines=""
for template in "$repo_root/.github/pull_request_template.md" "$repo_root/.gitlab/merge_request_templates/default.md"; do
  if [[ -f "$template" ]]; then
    while IFS= read -r line; do
      template_lines+="$(trim "$line")"$'\n'
    done <"$template"
  fi
done

section_lines() {
  awk -v heading="## $1" '
    /^## / { sub(/[[:space:]]+$/, ""); inside = ($0 == heading); next }
    inside { print }
  ' <<<"$body"
}

has_content() {
  local line trimmed
  while IFS= read -r line; do
    trimmed="$(trim "$line")"
    if [[ -z "$trimmed" || "$trimmed" =~ ^[-*]([[:space:]]+\[[[:space:]xX]\])?$ || "$trimmed" =~ ^\<!--.*--\>$ ]]; then
      continue
    fi
    if grep -Fx -- "$trimmed" <<<"$template_lines" >/dev/null; then
      continue
    fi
    return 0
  done < <(section_lines "$1")
  return 1
}

errors=()

for section in "${required_review_sections[@]}"; do
  if ! grep -E "^## ${section}[[:space:]]*$" <<<"$body" >/dev/null; then
    errors+=("missing required section: ## $section")
  elif ! has_content "$section"; then
    errors+=("section has no content beyond template placeholders: ## $section")
  fi
done

attribution_pattern='generated (with|by) .*(claude|codex|copilot|cursor|gpt|(^|[^[:alnum:]])ai([^[:alnum:]]|$))|🤖[[:space:]]*generated'
if attribution_lines="$(grep -inE "$attribution_pattern" <<<"$body")"; then
  errors+=("remove agent attribution lines:")
  while IFS= read -r line; do
    errors+=("  $line")
  done <<<"$attribution_lines"
fi

if (( ${#errors[@]} > 0 )); then
  printf 'repo-checks pr-body: %s\n' "${errors[@]}" >&2
  exit 1
fi

printf 'repo-checks pr-body: ok\n'
