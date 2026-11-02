#!/usr/bin/env node
/**
 * Runs the given command from this project's TRUE on-disk casing
 * (C:\...\CodeSage\frontend), regardless of what casing the invoking
 * terminal's cwd happens to have (e.g. "...\Codesage\frontend" —
 * Windows path autocomplete/history doesn't correct casing, and a
 * mismatch here makes webpack resolve some modules twice, once per
 * casing variant. For Next.js that has caused two separate copies of
 * next/dist/client/components/app-router.js to load at once, each with
 * its own React Context instance — producing a real client-side crash
 * ("Missing ActionQueueContext") on top of the slow, noisy
 * "multiple modules... differ in casing" webpack warnings.
 *
 * Fix: resolve the real, case-correct path via fs.realpathSync.native
 * (Windows-aware — returns the actual on-disk casing) and chdir into it
 * before spawning the real command, so every npm script always compiles
 * from one consistent path no matter how the terminal was cd'd.
 */
const { realpathSync } = require("fs");
const { spawnSync } = require("child_process");

const realCwd = realpathSync.native(process.cwd());
if (realCwd !== process.cwd()) {
  process.chdir(realCwd);
}

const [command, ...args] = process.argv.slice(2);
const result = spawnSync(command, args, {
  stdio: "inherit",
  shell: true,
  cwd: realCwd,
});

process.exit(result.status ?? 1);
