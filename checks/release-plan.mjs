// gh repo-checks release-plan: fail when a pending change record can never be consumed.
//
// `changeset version` skips private packages (unless privatePackages.version is set) and ignored packages, but it
// leaves a record that names one pending, including a `none` record. The release flow then keeps preparing a
// version pull request and never reaches publish mode.
import process from "node:process";

import { CheckError, readReleaseState } from "./release/changesets.mjs";

const usage = `Usage: gh repo-checks release-plan

Checks the pending .changeset/*.md records of the current repository. Needs
Node.js and the repository's installed @changesets/cli 3.x.`;

const args = process.argv.slice(2);
if (args.includes("-h") || args.includes("--help")) {
  console.log(usage);
  process.exit(0);
}
if (args.length > 0) {
  console.error(`repo-checks release-plan: unexpected argument: ${args[0]}`);
  console.error(usage);
  process.exit(1);
}

try {
  const { packages, config, plan, shouldSkipPackage } = await readReleaseState(process.cwd());
  const skipped = new Set(
    packages.packages
      .filter((pkg) =>
        shouldSkipPackage(pkg, { ignore: config.ignore, allowPrivatePackages: config.privatePackages.version })
      )
      .map((pkg) => pkg.packageJson.name)
  );
  const failures = plan.changesets.flatMap((changeset) => {
    const names = changeset.releases.filter((release) => skipped.has(release.name)).map((release) => release.name);
    return names.length > 0 ? [`.changeset/${changeset.id}.md names ${names.join(", ")}, which is not versioned`] : [];
  });
  if (failures.length > 0) {
    for (const failure of failures) {
      console.error(`repo-checks release-plan: ${failure}`);
    }
    process.exit(1);
  }
  console.log(`repo-checks release-plan: ok (${plan.changesets.length} pending change record(s))`);
} catch (error) {
  if (!(error instanceof CheckError)) {
    throw error;
  }
  console.error(`repo-checks release-plan: ${error.message}`);
  process.exit(1);
}
