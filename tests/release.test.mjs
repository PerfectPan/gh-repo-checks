// Tests for the release-plan and first-publish commands. They run the real dispatcher against generated
// workspaces whose node_modules/@changesets/cli links to an installed CLI, named by CHANGESETS_CLI_ROOT (a
// directory holding node_modules/@changesets/cli). See CONTRIBUTING.md for the install command.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { after, afterEach, before, describe, it } from "node:test";

const dispatcher = resolve(import.meta.dirname, "../gh-repo-checks");
const cliRoot = process.env.CHANGESETS_CLI_ROOT;
const cliDir = cliRoot && join(cliRoot, "node_modules/@changesets/cli");
if (!cliDir || !existsSync(join(cliDir, "package.json"))) {
  throw new Error("Set CHANGESETS_CLI_ROOT to a directory with node_modules/@changesets/cli; see CONTRIBUTING.md");
}

const workspaces = [];
afterEach(() => {
  for (const root of workspaces.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

/**
 * A pnpm workspace with public packages a and b, a private package u, and every package at 0.1.0 unless `versions`
 * names another version. `records` maps a record file name to its releases and `rawRecords` to its full text;
 * `config: null` writes no configuration. `peers` maps a package to its peer dependencies, and `repoChecksConf` is
 * the text of .github/repo-checks.conf.
 */
function workspace({
  records = {},
  rawRecords = {},
  ignore = [],
  fixed = [],
  linked = [],
  privateVersion = false,
  withCli = true,
  config,
  versions = {},
  peers = {},
  repoChecksConf
} = {}) {
  const root = mkdtempSync(join(tmpdir(), "gh-repo-checks-release-"));
  workspaces.push(root);
  const write = (path, content) => {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), typeof content === "string" ? content : JSON.stringify(content));
  };
  write("package.json", { name: "root", private: true });
  write("pnpm-workspace.yaml", "packages:\n  - packages/*\n");
  for (const name of ["a", "b", "u"]) {
    const manifest = { name, version: versions[name] ?? "0.1.0", private: name === "u" };
    write(`packages/${name}/package.json`, peers[name] ? { ...manifest, peerDependencies: peers[name] } : manifest);
  }
  if (config !== null) {
    write(
      ".changeset/config.json",
      config ?? { changelog: false, fixed, linked, ignore, privatePackages: { version: privateVersion, tag: false } }
    );
  }
  if (repoChecksConf !== undefined) {
    write(".github/repo-checks.conf", repoChecksConf);
  }
  for (const [id, text] of Object.entries(rawRecords)) {
    write(`.changeset/${id}.md`, text);
  }
  for (const [id, releases] of Object.entries(records)) {
    const frontmatter = Object.entries(releases)
      .map(([name, type]) => `"${name}": ${type}`)
      .join("\n");
    write(`.changeset/${id}.md`, `---\n${frontmatter}\n---\n\nNote.\n`);
  }
  if (withCli) {
    mkdirSync(join(root, "node_modules/@changesets"), { recursive: true });
    symlinkSync(cliDir, join(root, "node_modules/@changesets/cli"), "dir");
  }
  return root;
}

function run(root, args, env = {}) {
  return new Promise((done, reject) => {
    const child = spawn("bash", [dispatcher, ...args], {
      cwd: root,
      env: {
        ...process.env,
        // A per-workspace cache keeps npm from answering one test with another test's registry response, and the
        // update check would query the test registry for `npm` itself.
        npm_config_cache: join(root, ".npm"),
        npm_config_update_notifier: "false",
        npm_config_fetch_retries: "0",
        ...env
      },
      stdio: ["ignore", "pipe", "pipe"]
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (data) => (stdout += data));
    child.stderr.on("data", (data) => (stderr += data));
    child.on("error", reject);
    child.on("close", (status) => done({ status, stdout, stderr }));
  });
}

describe("release-plan", () => {
  it("accepts minor and patch records for public packages", async () => {
    const result = await run(workspace({ records: { one: { a: "minor", b: "patch" }, two: { a: "patch" } } }), [
      "release-plan"
    ]);

    assert.equal(result.stderr, "");
    assert.equal(result.status, 0);
    assert.match(result.stdout, /ok \(2 pending change record\(s\)\)/);
  });

  it("rejects a major record for a 0.x package", async () => {
    const result = await run(workspace({ records: { one: { a: "minor" }, two: { a: "major" } } }), ["release-plan"]);

    assert.equal(result.status, 1);
    assert.equal(
      result.stderr,
      "repo-checks release-plan: .changeset/two.md requests a major bump of a, a 0.x package; use minor for a " +
        'breaking change, or add "allow-major a" to .github/repo-checks.conf for a deliberate 1.0.0\n'
    );
  });

  it("accepts a major record for a 0.x package that the configuration allows", async () => {
    const root = workspace({
      records: { one: { a: "major" } },
      repoChecksConf: "# a goes 1.0.0 in this release.\nrequire .node-version\n  allow-major   a  \n"
    });

    const result = await run(root, ["release-plan"]);

    assert.equal(result.stderr, "");
    assert.equal(result.status, 0);
  });

  it("accepts a major record for a package past 0.x", async () => {
    const result = await run(workspace({ records: { one: { a: "major" } }, versions: { a: "1.2.0" } }), [
      "release-plan"
    ]);

    assert.equal(result.stderr, "");
    assert.equal(result.status, 0);
  });

  it("names a fixed-group member that an allowed major record moves to 1.0.0", async () => {
    const root = workspace({ records: { one: { a: "major" } }, fixed: [["a", "b"]], repoChecksConf: "allow-major a\n" });

    const result = await run(root, ["release-plan"]);

    assert.equal(result.status, 1);
    assert.equal(
      result.stderr,
      "repo-checks release-plan: the pending records bump b from 0.1.0 to 1.0.0 through its fixed or linked group; " +
        'add "allow-major b" to .github/repo-checks.conf for a deliberate 1.0.0\n'
    );
  });

  it("names a releasing linked-group member that a major record moves to 1.0.0", async () => {
    const root = workspace({
      records: { one: { a: "major" }, two: { b: "minor" } },
      linked: [["a", "b"]],
      repoChecksConf: "allow-major a\n"
    });

    const result = await run(root, ["release-plan"]);

    assert.equal(result.status, 1);
    assert.match(result.stderr, /bump b from 0\.1\.0 to 1\.0\.0 through its fixed or linked group/);
  });

  it("reports a refused major record once, beside the group members it carries", async () => {
    const root = workspace({ records: { one: { a: "major" } }, fixed: [["a", "b"]] });

    const result = await run(root, ["release-plan"]);

    assert.equal(result.status, 1);
    assert.match(result.stderr, /\.changeset\/one\.md requests a major bump of a, a 0\.x package/);
    assert.match(result.stderr, /bump b from 0\.1\.0 to 1\.0\.0 through its fixed or linked group/);
    assert.doesNotMatch(result.stderr, /bump a from/);
  });

  it("reports only the skipped package for a private package's major record", async () => {
    const result = await run(workspace({ records: { one: { u: "major" } } }), ["release-plan"]);

    assert.equal(result.status, 1);
    assert.equal(result.stderr, "repo-checks release-plan: .changeset/one.md names u, which is not versioned\n");
  });

  it("reads the configuration from the workspace root when run from a package directory", async () => {
    const root = workspace({ records: { one: { a: "major" } }, repoChecksConf: "allow-major a\n" });

    const result = await run(join(root, "packages/a"), ["release-plan"]);

    assert.equal(result.stderr, "");
    assert.equal(result.status, 0);
  });

  it("accepts a fixed group going 1.0.0 when the configuration allows every member", async () => {
    const root = workspace({
      records: { one: { a: "major" } },
      fixed: [["a", "b"]],
      repoChecksConf: "allow-major a\nallow-major b\n"
    });

    const result = await run(root, ["release-plan"]);

    assert.equal(result.stderr, "");
    assert.equal(result.status, 0);
  });

  it("accepts a minor record whose peer dependent stays 0.x", async () => {
    const root = workspace({ records: { one: { a: "minor" } }, peers: { b: { a: "^0.1.0" } } });

    const result = await run(root, ["release-plan"]);

    assert.equal(result.stderr, "");
    assert.equal(result.status, 0);
  });

  it("accepts a public package's none record", async () => {
    const result = await run(workspace({ records: { one: { a: "none" } } }), ["release-plan"]);

    assert.equal(result.status, 0);
  });

  for (const type of ["patch", "none"]) {
    it(`rejects a private package's ${type} record`, async () => {
      const result = await run(workspace({ records: { one: { u: type } } }), ["release-plan"]);

      assert.equal(result.status, 1);
      assert.match(result.stderr, /\.changeset\/one\.md names u, which is not versioned/);
    });

    it(`rejects an ignored package's ${type} record`, async () => {
      const result = await run(workspace({ records: { one: { a: type } }, ignore: ["a"] }), ["release-plan"]);

      assert.equal(result.status, 1);
      assert.match(result.stderr, /\.changeset\/one\.md names a, which is not versioned/);
    });
  }

  it("reports Changesets' own refusal of a record naming a private package beside a public one", async () => {
    const result = await run(workspace({ records: { mixed: { a: "minor", u: "minor" } } }), ["release-plan"]);

    assert.equal(result.status, 1);
    assert.match(result.stderr, /^repo-checks release-plan: Found mixed changeset mixed; /m);
    assert.doesNotMatch(result.stderr, /\n\s+at /, "prints Changesets' message without a stack trace");
  });

  it("accepts a private package's record when private packages are versioned", async () => {
    const result = await run(workspace({ records: { one: { u: "patch" } }, privateVersion: true }), ["release-plan"]);

    assert.equal(result.stderr, "");
    assert.equal(result.status, 0);
  });

  it("reports a malformed record without a stack trace", async () => {
    const result = await run(workspace({ rawRecords: { broken: '---\n"a": bogus\n---\n\nNote.\n' } }), [
      "release-plan"
    ]);

    assert.equal(result.status, 1);
    assert.match(result.stderr, /^repo-checks release-plan: /m);
    assert.doesNotMatch(result.stderr, /\n\s+at /);
  });

  it("reports a missing configuration without a stack trace", async () => {
    const result = await run(workspace({ config: null }), ["release-plan"]);

    assert.equal(result.status, 1);
    assert.match(result.stderr, /^repo-checks release-plan: .*config\.json/m);
    assert.doesNotMatch(result.stderr, /\n\s+at /);
  });

  it("says when @changesets/cli is not installed", async () => {
    const result = await run(workspace({ withCli: false }), ["release-plan"]);

    assert.equal(result.status, 1);
    assert.match(result.stderr, /@changesets\/cli is not installed here/);
  });

  it("reports an invalid configuration", async () => {
    const result = await run(workspace({ config: { changelog: false, access: "nope" } }), ["release-plan"]);

    assert.equal(result.status, 1);
    assert.match(result.stderr, /^repo-checks release-plan: invalid \.changeset\/config\.json: /m);
  });

  it("rejects arguments", async () => {
    const result = await run(workspace(), ["release-plan", "extra"]);

    assert.equal(result.status, 1);
    assert.match(result.stderr, /unexpected argument: extra/);
  });
});

describe("first-publish", () => {
  const queried = [];
  let published = new Set();
  let registryFailure = false;
  const registry = createServer((request, response) => {
    const name = decodeURIComponent(request.url?.slice(1) ?? "");
    queried.push(name);
    response.setHeader("content-type", "application/json");
    if (registryFailure || !published.has(name)) {
      response.statusCode = registryFailure ? 503 : 404;
      response.end(JSON.stringify({ error: registryFailure ? "Registry unavailable" : "Not found" }));
      return;
    }
    response.end(
      JSON.stringify({ name, "dist-tags": { latest: "0.0.0" }, versions: { "0.0.0": { name, version: "0.0.0" } } })
    );
  });
  const check = (root, mode) =>
    run(root, ["first-publish", ...(mode ? [mode] : [])], {
      RELEASE_REGISTRY: `http://127.0.0.1:${registry.address().port}/`
    });

  before(() => new Promise((done) => registry.listen(0, "127.0.0.1", done)));
  after(() => new Promise((done) => registry.close(() => done())));
  afterEach(() => {
    queried.length = 0;
    published = new Set();
    registryFailure = false;
  });

  it("checks only the release candidates in version mode, the default", async () => {
    published.add("a");
    const result = await check(workspace({ records: { one: { a: "patch" } } }));

    assert.equal(result.stderr, "");
    assert.equal(result.status, 0);
    assert.deepEqual(queried, ["a"]);
  });

  it("blocks a release candidate that has no version on npm", async () => {
    const result = await check(workspace({ records: { one: { a: "patch" } } }), "version");

    assert.equal(result.status, 1);
    assert.match(result.stderr, /no version on npm yet for a$/m);
  });

  it("checks every public, non-ignored package in publish mode", async () => {
    published.add("a");
    const result = await check(workspace({ ignore: ["b"] }), "publish");

    assert.equal(result.status, 0);
    assert.deepEqual(queried, ["a"]);
  });

  it("never checks a private package, even when private packages are versioned", async () => {
    published.add("a");
    published.add("b");
    const result = await check(workspace({ privateVersion: true }), "publish");

    assert.equal(result.status, 0);
    assert.deepEqual(queried.sort(), ["a", "b"]);
  });

  it("names every public package without a version in publish mode", async () => {
    const result = await check(workspace(), "publish");

    assert.equal(result.status, 1);
    assert.match(result.stderr, /no version on npm yet for a, b$/m);
  });

  it("distinguishes a registry failure from a missing package", async () => {
    registryFailure = true;
    const result = await check(workspace({ records: { one: { a: "patch" } } }));

    assert.equal(result.status, 1);
    assert.match(result.stderr, /registry lookup failed for a: /);
    assert.doesNotMatch(result.stderr, /no version on npm yet/);
  });

  it("rejects an unknown mode", async () => {
    const result = await check(workspace(), "release");

    assert.equal(result.status, 1);
    assert.match(result.stderr, /expected version or publish, got: release/);
  });
});
