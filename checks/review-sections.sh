# shellcheck shell=bash
# Sourced by repository.sh and pr-body.sh. This is the single list of `## `
# headings that every PR/MR template must contain and every PR/MR description
# must fill beyond template placeholders; other headings are optional. Adding a
# heading can fail downstream repositories, so it ships in a new major release.
# shellcheck disable=SC2034
required_review_sections=(
  "Summary"
  "Validation"
)
