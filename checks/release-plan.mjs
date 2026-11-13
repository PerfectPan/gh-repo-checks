// gh repo-checks release-plan: fail when the pending change records cannot be consumed, or would move a 0.x
// package to 1.0.0 without `allow-major`. The rules live in release/plan-rules.mjs.
import process from "node:process";

import { CheckError, readReleaseState } from "./release/changesets.mjs";
import { readAllowedMajors, releasePlanFailures } from "./release/plan-rules.mjs";

const usage = `Usage: gh repo-checks release-plan

Checks the pending .changeset/*.md records of the current repository: each
names only packages that changeset version releases, and none moves a 0.x
package to 1.0.0 unless .github/repo-checks.conf lists it as allow-major. Needs
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
  const state = await readReleaseState(process.cwd());
  const failures = releasePlanFailures(state, readAllowedMajors(state.packages.rootDir));
  if (failures.length > 0) {
    for (const failure of failures) {
      console.error(`repo-checks release-plan: ${failure}`);
    }
    process.exit(1);
  }
  console.log(`repo-checks release-plan: ok (${state.plan.changesets.length} pending change record(s))`);
} catch (error) {
  if (!(error instanceof CheckError)) {
    throw error;
  }
  console.error(`repo-checks release-plan: ${error.message}`);
  process.exit(1);
}
