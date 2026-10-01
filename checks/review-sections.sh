# shellcheck shell=bash
# Sourced by repository.sh and pr-body.sh. This is the single list of `## `
# headings that every PR/MR template and description must contain. Changing it
# can fail downstream repositories, so it ships in a new major release.
# shellcheck disable=SC2034
required_review_sections=(
  "Summary"
  "Motivation"
  "Implementation Notes"
  "Validation"
  "Evidence"
  "Safety Checklist"
  "Follow-up Risks"
)
