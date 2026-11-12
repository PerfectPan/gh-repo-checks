# npm Releases

PerfectPan repositories that publish to npm version with [Changesets](https://github.com/changesets/changesets)
and release through the shared workflow `.github/workflows/npm-release.yml` in this repository. Changesets owns
change records (`pnpm changeset`), version bumps and changelogs (`changeset version`) and publishing
(`changeset publish`). Packages publish through npm Trusted Publishing (OIDC) with provenance; no npm token is
stored anywhere. A merged version pull request publishes, and the workflow pushes one tag `<name>@<version>` and
creates one GitHub Release per published package.

| Step | Where | Result |
| --- | --- | --- |
| Change record | feature PR | `.changeset/<name>.md`, written with `pnpm changeset` or by hand |
| Version PR | the Release workflow, on a push to the default branch with pending records | draft PR `chore(release): version packages` from `changeset-release/<branch>`; its body lists each package's new changelog section |
| Version PR merge | GitHub, the release decision | bumped `package.json` versions and `CHANGELOG.md` files, no pending records |
| Publish | the Release workflow, on the merge push | gates and packing run, the packages publish, and the workflow pushes the tags and creates the GitHub Releases |

Each row is a separate completion state. A merged version PR is not a published release, and a started publish
run is not a published package.

## The Shared Workflow

Every run on the default branch goes through four jobs. Each job holds only the permissions it needs, so the job
that can request an OIDC token runs no repository build and no dependency lifecycle script.

1. **select release mode** (`contents: read`) installs the dependencies and runs
   `changesets/action/select-mode`: `version` while records that release something are pending, `publish` when
   none is pending and a public version is not on npm yet, `none` otherwise. A record written with
   `changeset add --empty` releases nothing, so with only such records pending the mode is `none`; the next
   version PR deletes them. In `version` mode it runs
   `gh repo-checks release-plan`; in `version` and `publish` mode it runs `gh repo-checks first-publish` unless
   `first-publish-check` is `false`. The checks come from the same commit of this repository as the workflow.
2. **version packages** (`contents: write`, `pull-requests: write`), in `version` mode, runs
   `changesets/action/version` with `version-command`. The command runs with `GITHUB_TOKEN` set, which
   `@changesets/changelog-github` needs for PR links and author thanks. The action commits through the GitHub
   API, so GitHub signs the commit, and opens or updates the draft version PR.
3. **check and pack packages** (`contents: read`), in `publish` mode, runs `check-command`, then
   `audit-command`, then `changesets/action/pack`, which packs each unpublished version with `pnpm pack`
   (replacing `workspace:` and `catalog:` ranges). `GH_TOKEN` is the job's read-only token, so a gate can use
   `gh`.
4. **publish packages** (`contents: write`, `id-token: write`) installs the dependencies with
   `--ignore-scripts` and runs `changesets/action/publish` on the packed tarballs: each one is published through
   Trusted Publishing, versions already on npm are skipped, and the action pushes the tags and creates the
   Releases.

A run on any other branch skips every job. The actions are pinned to an exact release tag because these jobs hold
write and OIDC permissions.

### Inputs and outputs

| Input | Default | Use |
| --- | --- | --- |
| `check-command` | `pnpm run check` | Release gate before packing. It must build what the packages ship. |
| `audit-command` | `pnpm audit --prod --audit-level=high` | Dependency audit after the gate; `''` skips it. Filter it to what ships, for example `pnpm --filter '!./apps/**' audit --prod --audit-level=high` when private apps share the workspace. |
| `version-command` | `pnpm run version-packages` | Versions the packages for the version PR. It runs without a shell, so `&&` does not chain commands; extend the root script instead when versioning also regenerates files. |
| `first-publish-check` | `true` | Runs `gh repo-checks first-publish` before versioning and publishing. |

Outputs: `published` (`"true"` when the run published something) and `published-packages` (a JSON array of
`{"name","version"}`), for a later job in the caller, such as building release binaries.

## Adopting

### Caller workflow

The calling file's name is what npm Trusted Publishing validates, so pick it once (`publish.yml`, or keep an
existing name that trusted publishers already use) and do not rename it without updating every package's trusted
publisher first.

```yaml
# The npm trusted publishers are bound to this file name; see docs/npm-release.md in PerfectPan/gh-repo-checks.
name: Release

on:
  push:
    branches: [main]
  # Rebuilds the version pull request from the current main, or retries a failed publish.
  workflow_dispatch: {}

permissions: {}

# A push waits for the running release, and GitHub keeps only the newest waiting run.
concurrency:
  group: release-${{ github.ref }}
  cancel-in-progress: false

jobs:
  release:
    uses: PerfectPan/gh-repo-checks/.github/workflows/npm-release.yml@v1
    permissions:
      contents: write
      pull-requests: write
      id-token: write
```

Pass inputs under `with:` only where the defaults do not fit. `@v1` follows compatible releases of this
repository; pin `@vX.Y.Z` to take each release through a reviewed PR instead.

### Repository files

- Root `devDependencies`: `@changesets/cli` 3.x and `@changesets/changelog-github`. The checks read the
  Changesets libraries through the installed CLI, so no other Changesets package is needed.
- Root scripts: `"changeset": "changeset"` and `"version-packages": "changeset version"`, extended when
  versioning also regenerates files.
- `.changeset/config.json`:

  ```json
  {
    "$schema": "https://unpkg.com/@changesets/config@4.0.0/schema.json",
    "changelog": ["@changesets/changelog-github", { "repo": "OWNER/REPO" }],
    "commit": false,
    "fixed": [],
    "linked": [],
    "access": "public",
    "baseBranch": "main",
    "updateInternalDependencies": "patch",
    "ignore": [],
    "privatePackages": { "version": false, "tag": false }
  }
  ```

  Put packages that release in lockstep into one `fixed` group. Naming the repository lets a local preview run
  with only `GITHUB_TOKEN` set.
- Each published `package.json`: `repository.url` pointing at this GitHub repository
  (`git+https://github.com/OWNER/REPO.git`, required by provenance), `publishConfig.access: "public"`, and a
  `files` list.
- Format checks skip the generated `CHANGELOG.md`: `@changesets/changelog-github` indents the blank lines of a
  multi-paragraph summary, which a formatter check rejects in the version PR. The shared `fmt` of
  `@perfectpan/lint-config` ignores `CHANGELOG.*` from the release that adds that default; keep it when a package
  overrides `ignorePatterns` (`[...fmt.ignorePatterns, "dist/**"]`), and add `CHANGELOG.*` yourself on an older
  lint-config.
- CI runs `gh repo-checks release-plan` on pull requests after the dependency install (see the README), so a
  record that can never be consumed fails before it merges.
- The repository's own release doc keeps only what is specific to it: the published packages and `fixed` groups,
  non-default inputs, its trusted-publisher values, and failure modes of its extra steps. It links here for the
  rest.

## Change Records

A PR that changes what a published package ships (source, manifest, build config) or the lockfile carries a
record. CI does not require one; the author adds it and the reviewer looks for it.

```bash
pnpm changeset add --patch @scope/pkg -m "Correct the export map."
```

`pnpm changeset` prompts for the same in a terminal. The summary becomes the changelog entry, so write it for
users of the package.

- Name only published packages. A record naming a private or ignored package is never consumed, and one naming a
  private package beside a public one makes `changeset version` fail; `gh repo-checks release-plan` rejects both,
  including `none` records. Describe a change in an internal package by its effect on the published package that
  ships it.
- The bump comes only from the records; the largest pending bump applies, and a `fixed` group shares it.
- `pnpm changeset status --verbose` previews the pending versions.

## One-Time Setup

### Repository

1. Keep the repository public: npm attaches provenance only for a public repository and package.
2. **Settings → Actions → General → Workflow permissions → Allow GitHub Actions to create and approve pull
   requests.** The version job fails without it.

### First publish

OIDC cannot create a package name, so `first-publish` stops the workflow until each new public name exists on npm.
A maintainer publishes a placeholder once, with their own npm login:

```bash
dir="$(mktemp -d)" && cd "$dir"
printf '{"name":"@scope/pkg","version":"0.0.0","description":"Placeholder; releases are published by CI."}\n' > package.json
npm publish --access public
npm deprecate @scope/pkg@0.0.0 "Placeholder; install a later version."
```

The scope must belong to an npm organization or user the maintainer owns. Re-run the failed run afterwards; it
opens the version PR. The placeholder never collides with real releases, which are higher.

### Trusted publisher, per package

On npmjs.com open the package **Settings → Trusted Publisher → GitHub Actions** and enter the owner, the
repository, the **caller's** workflow file name (for example `publish.yml`) and no environment. Enable direct
publishing ("Allow npm publish"); new configurations allow only staged publishing, which Changesets does not
support yet. The CLI equivalent (npm 11.15 or later, two-factor authentication on the account):

```bash
npm trust github @scope/pkg --repo OWNER/REPO --file publish.yml --allow-publish
npm trust list @scope/pkg
```

A new configuration expires unless a publish uses it within 2 days, so create it right before merging the first
version PR. Then, under **Publishing access**, select "Require two-factor authentication and disallow tokens".
One package's trusted publisher does not authorize another.

## Cutting a Release

1. Merge feature PRs with records. Each merge runs the Release workflow, which opens or updates the draft version
   PR; **Actions → Release → Run workflow** on the default branch rebuilds it on demand.
2. Every update returns the version PR to Draft (`pr-draft: always`), and pull request events created with the
   workflow token start no workflows. Review the version and changelog diff, then select **Ready for review** to
   start CI; GitHub can require **Approve workflows to run** for these events. Repeat after each update.
3. Merge once CI actually ran and passed for the current head. Merging is the release decision.
4. The merge push runs the workflow in `publish` mode: gates, pack, publish, tags and Releases.
5. Verify each package with `npm view <name>@<version>`, the tags with `git ls-remote --tags origin`, the GitHub
   Releases, and a clean install in a scratch project. Registry reads can lag a minute; retry the read, not the
   publish. The npm page shows a provenance badge linking to the run.

## Failure Recovery

The workflow publishes only when no record is pending; with records pending it prepares the version PR, even if
an earlier version is still unpublished. Recover by re-running the run of the release commit whenever possible.

- **select release mode failed**: `release-plan` names the record to fix or remove; `first-publish` names the
  package that needs its placeholder. Nothing was versioned or published.
- **version packages failed** (`version-command`, changelog lookup): nothing changed on the default branch.
  Re-run for a transient failure; otherwise fix the cause in a reviewed PR, whose merge regenerates the version
  PR.
- **check and pack failed**: nothing was tagged or published. Re-run for a transient failure. A fix without
  records publishes the same version from its merge push; a fix with records goes into the next version PR.
- **The merge run was cancelled or failed**: re-run that run; it keeps the merge commit, where no record is
  pending. Avoid merging PRs with records while it waits.
- **Publication stopped part-way**: re-run the failed run; `changeset publish` skips versions already on npm and
  tags the rest. Never bump the version to retry, and never unpublish.
- **Published, but the tag or Release is missing**: re-runs do not add them for a version already on npm. Create
  them on the release commit: `gh release create '<name>@X.Y.Z' --target <release commit>` with the changelog
  section as notes.
- **Trusted Publishing rejected a package**: check its trusted publisher (owner, repository, caller file name, no
  environment, direct publishing allowed) and re-run.
- **Bad published contents**: npm versions are immutable. `npm deprecate <name>@X.Y.Z "<reason>"` and release a
  fix; move `latest` back with `npm dist-tag add <name>@<previous> latest` when needed. Once a version is on npm,
  do not move or reuse its tag.
