// gh repo-checks first-publish: fail when a public package name that would be versioned or published has no
// version on npm yet.
//
// npm Trusted Publishing cannot create a package name, so publishing a new name fails at the token exchange after
// the version pull request was already merged. The check stops the release flow before that.
import process from "node:process";

import { CheckError, readReleaseState } from "./release/changesets.mjs";
import { lookUpPublishedVersions } from "./release/registry.mjs";

const usage = `Usage: gh repo-checks first-publish [version|publish]

version (default) checks the public packages the pending change records release,
so an unrelated new package does not block an existing package's version pull
request. publish checks every public, non-ignored package. RELEASE_REGISTRY
overrides the registry (default https://registry.npmjs.org/). Needs Node.js, npm
and the repository's installed @changesets/cli 3.x.`;

const args = process.argv.slice(2);
if (args.includes("-h") || args.includes("--help")) {
  console.log(usage);
  process.exit(0);
}
const mode = args[0] ?? "version";
if (args.length > 1 || (mode !== "version" && mode !== "publish")) {
  console.error(`repo-checks first-publish: expected version or publish, got: ${args.join(" ")}`);
  console.error(usage);
  process.exit(1);
}
const registry = process.env.RELEASE_REGISTRY || "https://registry.npmjs.org/";

try {
  const { packages, config, plan, shouldSkipPackage } = await readReleaseState(process.cwd());
  const candidates =
    mode === "version"
      ? new Set(plan.releases.filter((release) => release.type !== "none").map((release) => release.name))
      : undefined;
  const names = packages.packages
    .filter((pkg) => !shouldSkipPackage(pkg, { ignore: config.ignore, allowPrivatePackages: false }))
    .map((pkg) => pkg.packageJson.name)
    .filter((name) => candidates === undefined || candidates.has(name));

  const missing = [];
  for (const name of names) {
    const result = lookUpPublishedVersions(name, registry);
    if (result.error !== undefined) {
      console.error(`repo-checks first-publish: registry lookup failed for ${name}: ${result.error}`);
      process.exit(1);
    }
    if (!result.published) {
      missing.push(name);
    }
  }
  if (missing.length > 0) {
    console.error(`repo-checks first-publish: no version on npm yet for ${missing.join(", ")}`);
    console.error(
      "repo-checks first-publish: publish a placeholder version of each name first; " +
        "see First Publish in docs/npm-release.md of PerfectPan/gh-repo-checks"
    );
    process.exit(1);
  }
  console.log(`repo-checks first-publish: ok (${names.length} package(s))`);
} catch (error) {
  if (!(error instanceof CheckError)) {
    throw error;
  }
  console.error(`repo-checks first-publish: ${error.message}`);
  process.exit(1);
}
