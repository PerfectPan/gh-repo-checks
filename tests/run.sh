#!/usr/bin/env bash
# Self-test for every gh-repo-checks command. Every command runs under the bash
# that runs this file, so `/bin/bash tests/run.sh` covers macOS bash 3.2.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work="$(mktemp -d "${TMPDIR:-/tmp}/gh-repo-checks-test.XXXXXX")"
trap 'rm -rf "$work"' EXIT
# Fixture repositories must not resolve to a repository that encloses $work.
export GIT_CEILING_DIRECTORIES="$work"
# shellcheck source=checks/review-sections.sh
source "$root/checks/review-sections.sh"

# Built from pieces so this file does not trip the repository check itself.
fake_aws_key="AKIA""ABCDEFGHIJKLMNOP"
fake_home_path="/Users""/someone/project/notes.txt"
fake_placeholder="private""-token"

passed=0
failed=0
last_name=""
output=""

pass_case() {
  passed=$((passed + 1))
  printf 'ok    %s\n' "$1"
}

fail_case() {
  failed=$((failed + 1))
  printf 'FAIL  %s: %s\n' "$1" "$2"
  printf '%s\n' "$output" | sed 's/^/      | /'
}

# expect_ok NAME COMMAND...: COMMAND exits 0.
expect_ok() {
  local name="$1" status=0
  shift
  last_name="$name"
  output="$("$@" 2>&1)" || status=$?
  if (( status == 0 )); then
    pass_case "$name"
  else
    fail_case "$name" "expected exit 0, got $status"
  fi
}

# expect_error MESSAGE NAME COMMAND...: COMMAND fails and prints MESSAGE.
expect_error() {
  local message="$1" name="$2" status=0
  shift 2
  last_name="$name"
  output="$("$@" 2>&1)" || status=$?
  if (( status == 0 )); then
    fail_case "$name" "expected a failure, got exit 0"
  elif [[ "$output" != *"$message"* ]]; then
    fail_case "$name" "output lacks: $message"
  else
    pass_case "$name"
  fi
}

# expect_output TEXT: the previous command also printed TEXT.
expect_output() {
  if [[ "$output" == *"$1"* ]]; then
    pass_case "$last_name prints $1"
  else
    fail_case "$last_name" "output lacks: $1"
  fi
}

cli() {
  "$BASH" "$root/gh-repo-checks" "$@"
}

# in_repo DIR COMMAND...: run COMMAND inside DIR.
in_repo() {
  local dir="$1"
  shift
  (cd "$dir" && "$@")
}

# stdin_from FILE COMMAND...: run COMMAND with FILE on stdin.
stdin_from() {
  local file="$1"
  shift
  "$@" <"$file"
}

write_pr_template() {
  local section
  {
    printf '%s\n' "Title format: type(scope): summary, in English."
    for section in "${required_review_sections[@]}"; do
      printf '\n## %s\n\n-\n' "$section"
      if [[ "$section" == "Validation" ]]; then
        printf '%s\n' "- [ ] Repository checks: gh repo-checks repository"
      fi
    done
  } >"$1"
}

write_filled_body() {
  local section
  for section in "${required_review_sections[@]}"; do
    printf '## %s\n\n- Filled %s for this change.\n\n' "$section" "$section"
  done >"$1"
}

default_files=(
  AGENTS.md
  CONTRIBUTING.md
  README.md
  SECURITY.md
  LICENSE
  docs/README.md
  .editorconfig
  .gitignore
  .github/workflows/ci.yml
  docs/specs/0000-template.md
  docs/plans/0000-template.md
)

# new_repo NAME: create a staged fixture repository that passes the defaults.
new_repo() {
  local dir="$work/$1" file
  mkdir -p "$dir"
  git -C "$dir" init -q
  for file in "${default_files[@]}"; do
    mkdir -p "$dir/$(dirname "$file")"
    printf 'fixture\n' >"$dir/$file"
  done
  write_pr_template "$dir/.github/pull_request_template.md"
  git -C "$dir" add -A
  printf '%s\n' "$dir"
}

# put REPO PATH CONTENT: write PATH and stage it.
put() {
  mkdir -p "$1/$(dirname "$2")"
  printf '%s\n' "$3" >"$1/$2"
  git -C "$1" add -f -- "$2"
}

now() {
  perl -MTime::HiRes=time -e 'printf "%.3f\n", time'
}

printf 'bash %s\n\n' "$BASH_VERSION"

# --- dispatcher -------------------------------------------------------------

expect_error "Usage:" "dispatcher: no command" cli
expect_error "unknown command: nope" "dispatcher: unknown command" cli nope
expect_ok "dispatcher: help" cli --help
for command in pr-title pr-body repository protect; do
  expect_ok "dispatcher: $command --help" cli "$command" --help
done

# --- pr-title ---------------------------------------------------------------

for title in \
  "feat: add login" \
  "fix(api): handle a null body" \
  "feat(core)!: drop Node 18 support" \
  "chore(release): version packages" \
  "chore(deps): bump lodash to 4.17.21" \
  "docs(scope.name_x-1): update links"; do
  expect_ok "pr-title accepts: $title" cli pr-title "$title"
done

expect_error "missing PR title" "pr-title rejects an empty title" cli pr-title ""
expect_error "missing PR title" "pr-title rejects a blank title" cli pr-title "   "
for title in \
  "Feat: add login" \
  "feat:add login" \
  "feat: " \
  "feat(API): add login" \
  "feature: add login" \
  "update readme"; do
  expect_error "must match type(scope): summary" "pr-title rejects: $title" cli pr-title "$title"
done
for title in \
  "feat: 添加登录" \
  "docs: ドキュメントを更新" \
  "fix: 한국어 제목" \
  "fix(api): handle the colon："; do
  expect_error "CJK characters are not allowed" "pr-title rejects CJK: $title" cli pr-title "$title"
done
expect_error "CJK characters are not allowed" "pr-title rejects CJK under LC_ALL=C" \
  env LC_ALL=C "$BASH" "$root/gh-repo-checks" pr-title "feat: 添加登录"

# --- pr-body ----------------------------------------------------------------

body_repo="$(new_repo body)"
template="$body_repo/.github/pull_request_template.md"
filled="$work/filled.md"
write_filled_body "$filled"

expect_ok "pr-body accepts a filled body from a file" in_repo "$body_repo" cli pr-body "$filled"
expect_ok "pr-body accepts a filled body from stdin" stdin_from "$filled" in_repo "$body_repo" cli pr-body
expect_ok "pr-body accepts a filled body from -" stdin_from "$filled" in_repo "$body_repo" cli pr-body -

expect_error "no content beyond template placeholders: ## Summary" \
  "pr-body rejects the unchanged template" in_repo "$body_repo" cli pr-body "$template"
expect_output "no content beyond template placeholders: ## Validation"

template_validation="$work/template-validation.md"
awk '/^## Validation$/ { print; print ""; print "- [ ] Repository checks: gh repo-checks repository"; skip = 1; next }
     /^## / { skip = 0 }
     !skip { print }' "$filled" >"$template_validation"
expect_error "no content beyond template placeholders: ## Validation" \
  "pr-body treats template lines as placeholders" in_repo "$body_repo" cli pr-body "$template_validation"

attributed="$work/attributed.md"
{ cat "$filled"; printf '\n%s\n' "🤖 Generated with [Claude Code](https://claude.com/claude-code)"; } >"$attributed"
expect_error "remove agent attribution lines" "pr-body rejects a Claude Code attribution line" \
  in_repo "$body_repo" cli pr-body "$attributed"

whitespace="$work/whitespace.md"
printf '  \n\t\n   \n' >"$whitespace"
expect_error "missing PR body" "pr-body rejects a whitespace-only body" in_repo "$body_repo" cli pr-body "$whitespace"

missing_section="$work/missing-section.md"
grep -v '^## Evidence$' "$filled" >"$missing_section"
expect_error "missing required section: ## Evidence" "pr-body rejects a missing section" \
  in_repo "$body_repo" cli pr-body "$missing_section"

expect_error "file not found" "pr-body rejects a missing file" in_repo "$body_repo" cli pr-body "$work/absent.md"
expect_error "Usage:" "pr-body rejects two arguments" in_repo "$body_repo" cli pr-body a b

large="$work/large.md"
{
  for section in "${required_review_sections[@]}"; do
    printf '## %s\n\n- Filled %s for this change.\n' "$section" "$section"
    if [[ "$section" == "Implementation Notes" ]]; then
      for i in $(seq 1 250); do
        printf -- '- Note %d: a long implementation detail line for timing.\n' "$i"
      done
    fi
    printf '\n'
  done
} | perl -pe 's/\n/\r\n/' >"$large"
large_bytes="$(wc -c <"$large" | tr -d ' ')"
start="$(now)"
expect_ok "pr-body accepts a ${large_bytes}-byte CRLF body" in_repo "$body_repo" cli pr-body "$large"
elapsed="$(awk -v start="$start" -v end="$(now)" 'BEGIN { printf "%.2f", end - start }')"
if (( large_bytes >= 14000 )) && awk -v elapsed="$elapsed" 'BEGIN { exit !(elapsed < 2) }'; then
  pass_case "pr-body checks a ${large_bytes}-byte CRLF body in ${elapsed}s (< 2s)"
else
  fail_case "pr-body large body" "${large_bytes} bytes took ${elapsed}s"
fi

# --- repository: defaults ---------------------------------------------------

repo="$(new_repo defaults)"
expect_ok "repository passes the defaults" in_repo "$repo" cli repository
expect_ok "repository --staged passes the defaults" in_repo "$repo" cli repository --staged
expect_output "ok (staged)"

repo="$(new_repo ci-example)"
git -C "$repo" mv .github/workflows/ci.yml .github/workflows/ci.yml.example
expect_ok "repository accepts ci.yml.example instead of ci.yml" in_repo "$repo" cli repository

repo="$(new_repo missing)"
git -C "$repo" rm -q -f -- docs/plans/0000-template.md .github/workflows/ci.yml
expect_error "Missing required files" "repository reports missing default files" in_repo "$repo" cli repository
expect_output "  - docs/plans/0000-template.md"
expect_output "  - .github/workflows/ci.yml or .github/workflows/ci.yml.example"

repo="$(new_repo no-scripts)"
expect_ok "repository does not require copied check scripts" in_repo "$repo" cli repository

repo="$(new_repo artifact)"
put "$repo" node_modules/pkg/index.js "module.exports = 1;"
expect_error "Tracked local, generated, or machine-specific artifacts" \
  "repository rejects tracked node_modules" in_repo "$repo" cli repository

repo="$(new_repo secret)"
put "$repo" src/config.txt "key = $fake_aws_key"
expect_error "Potential secret, private path, or forbidden pattern" \
  "repository rejects an AWS access key" in_repo "$repo" cli repository
expect_output "src/config.txt:1:"

repo="$(new_repo private-path)"
put "$repo" docs/guide.md "Open $fake_home_path"
expect_error "Potential secret" "repository rejects a personal home path" in_repo "$repo" cli repository

repo="$(new_repo placeholder)"
put "$repo" docs/guide.md "token: $fake_placeholder"
expect_error "Potential secret" "repository rejects a private placeholder" in_repo "$repo" cli repository
put "$repo" docs/guide.md "clean"
put "$repo" AGENTS.md "Scan for $fake_placeholder before publishing."
expect_ok "repository skips AGENTS.md in the scan" in_repo "$repo" cli repository

repo="$(new_repo template-section)"
grep -v '^## Evidence$' "$repo/.github/pull_request_template.md" >"$work/pr-template.md"
put "$repo" .github/pull_request_template.md "$(cat "$work/pr-template.md")"
expect_error ".github/pull_request_template.md is missing required section: Evidence" \
  "repository rejects a PR template without a section" in_repo "$repo" cli repository

repo="$(new_repo arguments)"
mkdir -p "$work/plain"
expect_error "not inside a Git repository" "repository fails outside a Git repository" in_repo "$work/plain" cli repository
expect_error "unknown argument: --nope" "repository rejects unknown arguments" in_repo "$repo" cli repository --nope

# --- repository: GitLab -----------------------------------------------------

repo="$(new_repo gitlab)"
put "$repo" .gitlab/issue_templates/bug.md "Bug"
expect_error "  - .gitlab/merge_request_templates/default.md" \
  "repository requires the MR template when .gitlab/ exists" in_repo "$repo" cli repository
put "$repo" .gitlab/merge_request_templates/default.md "$(cat "$repo/.github/pull_request_template.md")"
expect_ok "repository accepts matching PR and MR templates" in_repo "$repo" cli repository
expect_ok "repository --staged accepts matching PR and MR templates" in_repo "$repo" cli repository --staged
put "$repo" .gitlab/merge_request_templates/default.md "$(cat "$work/pr-template.md")"
expect_error ".gitlab/merge_request_templates/default.md is missing required section: Evidence" \
  "repository checks the MR template sections" in_repo "$repo" cli repository

# --- repository: .github/repo-checks.conf -----------------------------------

repo="$(new_repo conf-require)"
put "$repo" .github/repo-checks.conf "# Extra files for this repository.
require .node-version
require .github/dependabot.yml|.github/renovate.json"
expect_error "  - .node-version" "conf require adds a required file" in_repo "$repo" cli repository
expect_output "  - .github/dependabot.yml or .github/renovate.json"
put "$repo" .node-version "22"
put "$repo" .github/renovate.json "{}"
expect_ok "conf require accepts present files and alternatives" in_repo "$repo" cli repository

repo="$(new_repo conf-unrequire)"
git -C "$repo" rm -q -r -f -- docs .github/workflows/ci.yml
put "$repo" .github/repo-checks.conf "unrequire docs/README.md
unrequire docs/specs/0000-template.md
unrequire docs/plans/0000-template.md
unrequire .github/workflows/ci.yml"
expect_ok "conf unrequire drops default files" in_repo "$repo" cli repository
put "$repo" .github/repo-checks.conf "unrequire specs/0000-template.md"
expect_error "repo-checks.conf:1: not a default requirement: specs/0000-template.md" \
  "conf unrequire rejects unknown requirements" in_repo "$repo" cli repository

repo="$(new_repo conf-forbid)"
put "$repo" .github/repo-checks.conf "forbid registry\\.corp\\.test"
expect_ok "conf forbid does not flag the config file itself" in_repo "$repo" cli repository
put "$repo" package.json '{"publishConfig": {"registry": "https://registry.corp.test/"}}'
expect_error "package.json:1:" "conf forbid rejects a matching file" in_repo "$repo" cli repository
put "$repo" .github/repo-checks.conf "forbid registry\\.corp\\.test
exclude package.json"
expect_ok "conf exclude skips a path in the scan" in_repo "$repo" cli repository

repo="$(new_repo conf-exclude-dir)"
put "$repo" tests/fixtures/leak.txt "$fake_aws_key"
put "$repo" .github/repo-checks.conf "exclude tests/fixtures"
expect_ok "conf exclude skips a directory in the scan" in_repo "$repo" cli repository

repo="$(new_repo conf-errors)"
put "$repo" .github/repo-checks.conf "

  # indented comment
require"
expect_error "repo-checks.conf:4: missing value for require" "conf rejects a directive without a value" \
  in_repo "$repo" cli repository
put "$repo" .github/repo-checks.conf "run node scripts/check.mjs"
expect_error "repo-checks.conf:1: unknown directive: run" "conf rejects unknown directives" \
  in_repo "$repo" cli repository
put "$repo" .github/repo-checks.conf "forbid (unclosed"
expect_error "git grep failed" "conf rejects an invalid forbid pattern" in_repo "$repo" cli repository

# --- repository --staged ----------------------------------------------------

repo="$(new_repo staged)"
printf '%s\n' "key = $fake_aws_key" >>"$repo/README.md"
expect_error "Potential secret" "repository scans unstaged working tree edits" in_repo "$repo" cli repository
expect_ok "repository --staged ignores unstaged edits" in_repo "$repo" cli repository --staged
git -C "$repo" add README.md
expect_error "Potential secret" "repository --staged scans staged content" in_repo "$repo" cli repository --staged

repo="$(new_repo staged-files)"
rm "$repo/docs/README.md"
expect_error "  - docs/README.md" "repository checks working tree files" in_repo "$repo" cli repository
expect_ok "repository --staged checks index files" in_repo "$repo" cli repository --staged

repo="$(new_repo staged-conf)"
put "$repo" .github/repo-checks.conf "require .node-version"
printf '\n' >"$repo/.github/repo-checks.conf"
expect_ok "repository reads the working tree config" in_repo "$repo" cli repository
expect_error "  - .node-version" "repository --staged reads the staged config" in_repo "$repo" cli repository --staged

repo="$(new_repo staged-artifact)"
put "$repo" dist/app.js "bundle"
expect_error "Tracked local, generated, or machine-specific artifacts" \
  "repository --staged rejects staged artifacts" in_repo "$repo" cli repository --staged

# --- protect ----------------------------------------------------------------

expect_ok "protect dry run with --approvals 0 and --check" \
  cli protect --repo owner/repo --branch main --approvals 0 --check test --check lint
expect_output '"required_approving_review_count": 0'
expect_output '"require_last_push_approval": false'
expect_output '"contexts": ["repository checks", "conventional PR title", "PR description", "test", "lint"]'
expect_output "Dry run only."

expect_ok "protect dry run with default approvals" cli protect --repo owner/repo --branch main
expect_output '"required_approving_review_count": 1'
expect_output '"require_last_push_approval": true'
expect_output '"contexts": ["repository checks", "conventional PR title", "PR description"]'

expect_error "--approvals must be a non-negative integer" "protect rejects bad approvals" \
  cli protect --repo owner/repo --branch main --approvals many
expect_error "invalid check name" "protect rejects a quoted check name" \
  cli protect --repo owner/repo --branch main --check 'bad"name'
expect_error "--repo must use OWNER/REPO format" "protect rejects a bad repo" \
  cli protect --repo repo-only --branch main

printf '\n%d passed, %d failed (bash %s)\n' "$passed" "$failed" "$BASH_VERSION"
(( failed == 0 ))
