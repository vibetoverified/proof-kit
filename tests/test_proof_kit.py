"""Tests for Proof Kit. Run from products/proof-kit:  python -m unittest discover -s tests -v"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))

from proof_kit import proof_init  # noqa: E402
from proof_kit.common import _tail, load_config, parse_toml, read_hook_input  # noqa: E402

HOOK = KIT / "proof_kit" / "verify_before_stop.py"
PY = sys.executable
PASS = f'"{PY}" -c "print(\'ok\')"'
FAIL = f'"{PY}" -c "import sys; print(\'4 tests failed\'); sys.exit(1)"'


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class Project:
    """A throwaway git repo with a proof.toml."""

    def __init__(self, checks: dict, extra: str = "", changed: bool = True):
        self.root = Path(tempfile.mkdtemp(prefix="proofkit-"))
        body = "[checks]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in checks.items())
        (self.root / "proof.toml").write_text(body + "\n[stop_hook]\n" + extra, encoding="utf-8")
        (self.root / ".gitignore").write_text(".proof/\n", encoding="utf-8")
        git(self.root, "init", "-q")
        git(self.root, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
        git(self.root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
        if changed:
            (self.root / "app.py").write_text("x = 1\n", encoding="utf-8")

    def stop(self, session: str = "s1"):
        payload = json.dumps({"cwd": str(self.root), "session_id": session, "stop_hook_active": False})
        return subprocess.run([PY, str(HOOK)], input=payload, capture_output=True, text=True, timeout=120)

    def evidence(self) -> str:
        return (self.root / ".proof" / "last-run.md").read_text(encoding="utf-8")

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


@unittest.skipUnless(shutil.which("git"), "git is required")
class StopHookTests(unittest.TestCase):
    def make(self, *args, **kwargs) -> Project:
        p = Project(*args, **kwargs)
        self.addCleanup(p.cleanup)
        return p

    def test_failing_check_blocks_with_reason(self):
        p = self.make({"test": FAIL})
        r = p.stop()
        self.assertEqual(r.returncode, 2)
        self.assertIn("4 tests failed", r.stderr)
        self.assertIn("do not skip, delete or weaken tests", r.stderr)
        self.assertIn("FAIL (exit 1)", p.evidence())

    def test_passing_checks_allow_stop_and_write_evidence(self):
        p = self.make({"test": PASS, "lint": PASS})
        r = p.stop()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("all checks passed", p.evidence())

    def test_gives_up_after_max_attempts(self):
        p = self.make({"test": FAIL}, extra="max_attempts = 2\n")
        self.assertEqual(p.stop().returncode, 2)
        self.assertEqual(p.stop().returncode, 2)
        final = p.stop()
        self.assertEqual(final.returncode, 0)
        self.assertIn("handed back", p.evidence())
        self.assertEqual(p.stop().returncode, 2, "counter resets after handing back")
        history = (p.root / ".proof" / "history.log").read_text(encoding="utf-8")
        self.assertEqual([ln.split("\t")[2] for ln in history.splitlines()],
                         ["blocked", "blocked", "handed_back", "blocked"])

    def test_sessions_are_counted_separately(self):
        p = self.make({"test": FAIL}, extra="max_attempts = 1\n")
        self.assertEqual(p.stop("a").returncode, 2)
        self.assertEqual(p.stop("b").returncode, 2)
        self.assertEqual(p.stop("a").returncode, 0)

    def test_no_changes_skips_checks(self):
        p = self.make({"test": FAIL}, changed=False)
        self.assertEqual(p.stop().returncode, 0)
        self.assertFalse((p.root / ".proof" / "last-run.md").exists())

    def test_disabled_hook_allows_stop(self):
        p = self.make({"test": FAIL}, extra="enabled = false\n")
        self.assertEqual(p.stop().returncode, 0)

    def test_timeout_counts_as_failure(self):
        slow = f'"{PY}" -c "import time; time.sleep(5)"'
        p = self.make({"test": slow}, extra="timeout_seconds = 1\n")
        r = p.stop()
        self.assertEqual(r.returncode, 2)
        self.assertIn("timed out", r.stderr.lower())

    def test_no_proof_toml_allows_stop(self):
        root = Path(tempfile.mkdtemp(prefix="proofkit-"))
        self.addCleanup(shutil.rmtree, root, True)
        payload = json.dumps({"cwd": str(root), "session_id": "s"})
        r = subprocess.run([PY, str(HOOK)], input=payload, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)

    def test_bad_input_never_breaks_session(self):
        r = subprocess.run([PY, str(HOOK)], input="not json", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)

    def test_reads_input_piped_from_windows_powershell(self):
        # Windows PowerShell puts a UTF-8 byte-order mark in front of piped text.
        p = self.make({"test": FAIL})
        payload = json.dumps({"cwd": str(p.root), "session_id": "s1"}).encode("utf-8")
        r = subprocess.run([PY, str(HOOK)], input=b"\xef\xbb\xbf" + payload, capture_output=True, timeout=120)
        self.assertEqual(r.returncode, 2, r.stderr)


class HookInputTests(unittest.TestCase):
    def test_bom_non_ascii_and_empty_input(self):
        payload = {"cwd": "C:\\Users\\Zoë\\café", "session_id": "s"}
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.assertEqual(read_hook_input(io.BytesIO(raw)), payload)
        self.assertEqual(read_hook_input(io.BytesIO(b"\xef\xbb\xbf" + raw + b"\r\n")), payload)
        self.assertEqual(read_hook_input(io.BytesIO(b"")), {})
        self.assertEqual(read_hook_input(io.BytesIO(b"\xef\xbb\xbf\r\n")), {})

    def test_rejects_non_objects(self):
        for raw in (b"not json", b"[1, 2]", b"\xff\xfe{}"):
            with self.assertRaises(ValueError, msg=raw):
                read_hook_input(io.BytesIO(raw))


class ConfigTests(unittest.TestCase):
    def test_parser_handles_comments_quotes_and_types(self):
        text = (
            '[checks]\ntest = "npm test # not a comment"  # comment\nlint = \'ruff check .\'\n'
            "[stop_hook]\nenabled = false\nmax_attempts = 5\n"
        )
        data = parse_toml(text)
        self.assertEqual(data["checks"]["test"], "npm test # not a comment")
        self.assertEqual(data["checks"]["lint"], "ruff check .")
        self.assertIs(data["stop_hook"]["enabled"], False)
        self.assertEqual(data["stop_hook"]["max_attempts"], 5)

    def test_long_output_keeps_failure_lines(self):
        noise = [f"    at frame {i}" for i in range(80)]
        text = "\n".join(["✖ blocks the 6th request", *noise, "ℹ fail 4", *noise, "done"])
        tail = _tail(text)
        self.assertIn("✖ blocks the 6th request", tail)
        self.assertIn("ℹ fail 4", tail)
        self.assertIn("lines condensed", tail)
        self.assertLess(len(tail.splitlines()), 45)
        self.assertEqual(_tail("a\nb"), "a\nb")

    def test_defaults_fill_missing_settings(self):
        root = Path(tempfile.mkdtemp(prefix="proofkit-"))
        self.addCleanup(shutil.rmtree, root, True)
        (root / "proof.toml").write_text('[checks]\ntest = "x"\n', encoding="utf-8")
        cfg = load_config(root)
        self.assertEqual(cfg["stop_hook"]["max_attempts"], 3)
        self.assertTrue(cfg["stop_hook"]["only_if_changed"])


class InitTests(unittest.TestCase):
    def tmp(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="proofkit-"))
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def test_detects_node_project(self):
        root = self.tmp()
        (root / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run", "lint": "eslint ."}}))
        (root / "tsconfig.json").write_text("{}")
        checks = proof_init.detect_checks(root, "python3")
        self.assertEqual(checks, {"test": "npm test --silent", "lint": "npm run lint --silent",
                                  "types": "npx tsc --noEmit"})

    def test_ignores_npm_placeholder_test_and_uses_pnpm(self):
        root = self.tmp()
        (root / "package.json").write_text(json.dumps({"scripts": {"test": proof_init.DEFAULT_NPM_TEST,
                                                                   "lint": "eslint ."}}))
        (root / "pnpm-lock.yaml").write_text("")
        self.assertEqual(proof_init.detect_checks(root, "python3"), {"lint": "pnpm run lint"})

    def test_detects_python_project(self):
        root = self.tmp()
        (root / "pyproject.toml").write_text("[tool.ruff]\n[project.optional-dependencies]\ndev=['pytest','mypy']\n")
        checks = proof_init.detect_checks(root, "python3")
        self.assertEqual(checks, {"test": "python3 -m pytest -q", "lint": "python3 -m ruff check .",
                                  "types": "python3 -m mypy ."})

    def test_init_installs_everything_and_is_rerunnable(self):
        root = self.tmp()
        (root / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}))
        (root / ".claude").mkdir()
        (root / ".claude" / "settings.local.json").write_text(json.dumps(
            {"permissions": {"allow": ["Bash(ls)"]},
             "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}))
        for _ in range(2):
            self.assertEqual(proof_init.main(["--root", str(root)]), 0)

        self.assertIn('test = "npm test --silent"', (root / "proof.toml").read_text())
        self.assertTrue((root / ".claude" / "proof-kit" / "proof_kit" / "verify_before_stop.py").is_file())
        self.assertTrue((root / ".claude" / "skills" / "prove-it" / "SKILL.md").is_file())
        self.assertIn(".proof/", (root / ".gitignore").read_text())
        self.assertEqual((root / ".gitignore").read_text().count(".proof/"), 1)

        settings = json.loads((root / ".claude" / "settings.local.json").read_text())
        self.assertEqual(settings["permissions"], {"allow": ["Bash(ls)"]}, "existing settings kept")
        commands = [h for g in settings["hooks"]["Stop"] for h in g["hooks"]]
        ours = [h for h in commands if proof_init.HOOK_ARG in h.get("args", [])]
        self.assertEqual(len(ours), 1, "re-running init does not duplicate the hook")
        self.assertEqual(len(commands), 2, "the user's own Stop hook is kept")
        self.assertTrue(Path(ours[0]["command"]).name.startswith("py"))

    def test_installed_copy_runs_as_a_hook(self):
        if not shutil.which("git"):
            self.skipTest("git is required")
        p = Project({"test": FAIL})
        self.addCleanup(p.cleanup)
        proof_init.main(["--root", str(p.root)])
        hook = p.root / ".claude" / "proof-kit" / "proof_kit" / "verify_before_stop.py"
        payload = json.dumps({"cwd": str(p.root), "session_id": "x"})
        r = subprocess.run([PY, str(hook)], input=payload, capture_output=True, text=True, cwd=p.root)
        self.assertEqual(r.returncode, 2, r.stderr)


if __name__ == "__main__":
    unittest.main()
