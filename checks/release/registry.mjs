import { execFileSync } from "node:child_process";

/**
 * Asks the registry whether a package name has any published version. A 404 means the name does not exist yet;
 * any other failure is not evidence either way, so it is returned as an error instead of a missing name.
 */
export function lookUpPublishedVersions(name, registry) {
  let output;
  try {
    output = execFileSync("npm", ["view", name, "versions", "--json", "--registry", registry], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"]
    });
  } catch (error) {
    const stderr = String(error?.stderr ?? error?.message ?? "");
    if (stderr.includes("E404")) {
      return { published: false };
    }
    return { error: stderr.trim().split("\n")[0] || "npm view failed" };
  }
  const versions = JSON.parse(output);
  return { published: Array.isArray(versions) && versions.length > 0 };
}
