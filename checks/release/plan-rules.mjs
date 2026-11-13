// The rules of `gh repo-checks release-plan`, applied to a release state from changesets.mjs.
//
// `changeset version` skips private packages (unless privatePackages.version is set) and ignored packages, but it
// leaves a record that names one pending, including a `none` record. The release flow then keeps preparing a
// version pull request and never reaches publish mode.
//
// A major bump moves a 0.x package to 1.0.0, which a breaking change in 0.x does not need: a minor bump already
// signals it. Changesets also raises every releasing member of a `fixed` or `linked` group to the group's largest
// bump, so one major record can move other packages to 1.0.0. Going 1.0.0 is a deliberate decision, recorded per
// package with `allow-major` in .github/repo-checks.conf.
import { readFileSync } from "node:fs";
import { join } from "node:path";

export const CONFIG_PATH = ".github/repo-checks.conf";

/**
 * The `allow-major` values of the repository's configuration. The repository check validates the file, so the other
 * directives are skipped here.
 */
export function readAllowedMajors(rootDir) {
  let text;
  try {
    text = readFileSync(join(rootDir, CONFIG_PATH), "utf8");
  } catch (error) {
    if (error.code === "ENOENT") {
      return new Set();
    }
    throw error;
  }
  const names = new Set();
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const directive = line.split(/\s/, 1)[0];
    if (directive === "allow-major") {
      names.add(line.slice(directive.length).trim());
    }
  }
  return names;
}

const allowance = (name) => `add "allow-major ${name}" to ${CONFIG_PATH} for a deliberate 1.0.0`;

/** The failure messages for a release state: per record in record order, then the bumps a group carries. */
export function releasePlanFailures({ packages, config, plan, shouldSkipPackage }, allowedMajors) {
  const skipped = new Set(
    packages.packages
      .filter((pkg) =>
        shouldSkipPackage(pkg, { ignore: config.ignore, allowPrivatePackages: config.privatePackages.version })
      )
      .map((pkg) => pkg.packageJson.name)
  );
  const planned = new Map(plan.releases.map((release) => [release.name, release]));
  const reachesOne = (name) => {
    const release = planned.get(name);
    return (
      release !== undefined &&
      release.type === "major" &&
      release.oldVersion.startsWith("0.") &&
      !allowedMajors.has(name)
    );
  };

  const failures = [];
  const requested = new Set();
  for (const changeset of plan.changesets) {
    const record = `.changeset/${changeset.id}.md`;
    const names = changeset.releases.filter((release) => skipped.has(release.name)).map((release) => release.name);
    if (names.length > 0) {
      failures.push(`${record} names ${names.join(", ")}, which is not versioned`);
    }
    for (const release of changeset.releases) {
      if (release.type === "major" && reachesOne(release.name)) {
        requested.add(release.name);
        failures.push(
          `${record} requests a major bump of ${release.name}, a 0.x package; use minor for a breaking change, or ` +
            allowance(release.name)
        );
      }
    }
  }
  for (const release of plan.releases) {
    if (reachesOne(release.name) && !requested.has(release.name)) {
      failures.push(
        `the pending records bump ${release.name} from ${release.oldVersion} to ${release.newVersion} through its ` +
          `fixed or linked group; ${allowance(release.name)}`
      );
    }
  }
  return failures;
}
