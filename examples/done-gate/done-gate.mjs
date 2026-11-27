// done-gate: Claude Code may only stop when your check passes.
// Stop hook. Usage: node done-gate.mjs <check command>, for example: node done-gate.mjs npm test
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const check = process.argv.slice(2).join(" ") || "npm test";
const event = JSON.parse(readFileSync(0, "utf8")); // Claude Code sends the Stop event on stdin
const sh = (command) => spawnSync(command, { shell: true, encoding: "utf8" });

// Nothing changed (a question, a plan): nothing to prove.
const changes = sh("git status --porcelain -- .");
if (changes.status === 0 && changes.stdout.trim() === "") process.exit(0);

const run = sh(check);
if (run.status === 0) process.exit(0); // passed: the agent may stop

// stop_hook_active is true when the agent is only still going because a Stop hook blocked it.
const counter = join(tmpdir(), `done-gate-${event.session_id}`);
const blocks = event.stop_hook_active && existsSync(counter) ? Number(readFileSync(counter, "utf8")) : 0;
if (blocks >= 3) {
  console.log(JSON.stringify({ systemMessage: `done-gate: ${check} still fails after 3 blocks. Over to you.` }));
  process.exit(0); // let it stop, and tell the human why
}
writeFileSync(counter, String(blocks + 1));

console.error(`done-gate: ${check} failed (block ${blocks + 1} of 3). You're not done.`);
console.error("Fix the cause. Don't skip, delete or weaken tests.\n");
console.error(run.stdout + run.stderr);
process.exit(2); // exit code 2: Claude can't stop, and reads this message
