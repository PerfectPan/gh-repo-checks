// Reads a repository's Changesets state with the libraries its own @changesets/cli depends on. The checks then
// read the configuration and plan a release exactly as the installed CLI does, and the repository declares no
// dependency beyond @changesets/cli.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const SUPPORTED_CLI_MAJOR = "3";

export class CheckError extends Error {}

const messageOf = (error) => (error instanceof Error ? error.message : String(error)).replaceAll("\n", "; ");

async function loadLibraries(cwd) {
  const fromRepository = createRequire(join(cwd, "package.json"));
  let cliManifestPath;
  try {
    cliManifestPath = fromRepository.resolve("@changesets/cli/package.json");
  } catch {
    throw new CheckError("@changesets/cli is not installed here; install the repository's dependencies first");
  }
  const { version } = JSON.parse(readFileSync(cliManifestPath, "utf8"));
  if (typeof version !== "string" || version.split(".")[0] !== SUPPORTED_CLI_MAJOR) {
    throw new CheckError(`@changesets/cli ${version} is not supported; these checks need version ${SUPPORTED_CLI_MAJOR}.x`);
  }
  const fromCli = createRequire(cliManifestPath);
  // These are the CLI's own dependencies, not its public API; a 3.x release that drops one fails here by name.
  const load = async (name) => {
    try {
      return await import(pathToFileURL(fromCli.resolve(name)).href);
    } catch (error) {
      throw new CheckError(`cannot load ${name} through @changesets/cli ${version}: ${messageOf(error)}`);
    }
  };
  const [config, read, pre, assemble, skip, packages] = await Promise.all([
    load("@changesets/config"),
    load("@changesets/read"),
    load("@changesets/pre"),
    load("@changesets/assemble-release-plan"),
    load("@changesets/should-skip-package"),
    load("@manypkg/get-packages")
  ]);
  return {
    readConfig: config.readConfig,
    readChangesets: read.readChangesets,
    readPreState: pre.readPreState,
    assembleReleasePlan: assemble.assembleReleasePlan,
    shouldSkipPackage: skip.shouldSkipPackage,
    getPackages: packages.getPackages
  };
}

/**
 * Loads the workspace packages, the parsed `.changeset/config.json` and the pending release plan, the same steps
 * `@changesets/get-release-plan` takes. Changesets reports a missing configuration, a malformed record, and a
 * record it refuses (such as one naming a skipped package beside a released one) through plain errors; they
 * surface as a CheckError with Changesets' message.
 */
export async function readReleaseState(cwd) {
  const lib = await loadLibraries(cwd);
  try {
    const packages = await lib.getPackages(cwd);
    const { config, errors } = await lib.readConfig(packages.rootDir, packages);
    if (!config) {
      throw new CheckError(`invalid .changeset/config.json: ${errors.join("; ")}`);
    }
    const changesets = await lib.readChangesets(packages.rootDir);
    const preState = await lib.readPreState(packages.rootDir);
    const plan = lib.assembleReleasePlan(changesets, packages, config, preState);
    return { packages, config, plan, shouldSkipPackage: lib.shouldSkipPackage };
  } catch (error) {
    throw error instanceof CheckError ? error : new CheckError(messageOf(error));
  }
}
