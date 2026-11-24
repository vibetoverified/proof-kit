"""Set up Proof Kit in a project: detect its checks, write proof.toml, install the skills and hooks.

Usage, from the project's root folder:
    python path/to/proof-kit/install.py            # set up
    python path/to/proof-kit/install.py --dry-run  # show what it would do
    python path/to/proof-kit/install.py --force    # overwrite an existing proof.toml
    python path/to/proof-kit/install.py --ci       # also add the GitHub Actions workflow (full edition)

What it changes in the project:
    proof.toml                          the commands that prove the work (edit freely)
    .claude/proof-kit/proof_kit/        the hook scripts (copied, so the project is self-contained)
    .claude/skills/                     the skills (prove-it; the full edition adds self-review,
                                        security-pass and handoff)
    .claude/settings.local.json         the hooks, using this machine's Python (not committed)
    .github/workflows/proof.yml         with --ci (full edition)
    .gitignore                          adds .proof/ (run state and evidence)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

KIT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_NPM_TEST = 'echo "Error: no test specified" && exit 1'
HOOK_DIR = "${CLAUDE_PROJECT_DIR}/.claude/proof-kit/proof_kit/"
HOOK_ARG = HOOK_DIR + "verify_before_stop.py"
GUARD_TIMEOUT = 30
# (event, matcher, script) for the full edition's guards
GUARDS = (
    ("PostToolUse", "Edit|MultiEdit|Write", "tamper_guard.py"),
    ("PreToolUse", "Read|Edit|MultiEdit|Write|Grep|Bash", "secrets_guard.py"),
)


# ---------- detection ----------

def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _node_checks(root: Path) -> Dict[str, str]:
    package = root / "package.json"
    if not package.is_file():
        return {}
    try:
        scripts = json.loads(_read(package)).get("scripts", {}) or {}
    except ValueError:
        scripts = {}
    if (root / "pnpm-lock.yaml").exists():
        pm, run, exe = "pnpm", "pnpm run", "pnpm exec"
    elif (root / "yarn.lock").exists():
        pm, run, exe = "yarn", "yarn run", "yarn"
    elif (root / "bun.lockb").exists() or (root / "bun.lock").exists():
        pm, run, exe = "bun", "bun run", "bunx"
    else:
        pm, run, exe = "npm", "npm run", "npx"

    checks: Dict[str, str] = {}
    test = scripts.get("test", "")
    if test and test.strip() != DEFAULT_NPM_TEST:
        checks["test"] = f"{pm} test --silent" if pm == "npm" else f"{pm} test"
    if scripts.get("lint"):
        checks["lint"] = f"{run} lint --silent" if pm == "npm" else f"{run} lint"
    if scripts.get("typecheck"):
        checks["types"] = f"{run} typecheck"
    elif (root / "tsconfig.json").exists():
        checks["types"] = f"{exe} tsc --noEmit"
    return checks


def _python_cmd(root: Path, fallback: str) -> str:
    if (root / ".venv" / "Scripts" / "python.exe").exists():
        return r".venv\Scripts\python"
    if (root / ".venv" / "bin" / "python").exists():
        return ".venv/bin/python"
    return fallback


def _python_checks(root: Path, python: str) -> Dict[str, str]:
    markers = ["pyproject.toml", "setup.cfg", "setup.py", "requirements.txt", "requirements-dev.txt"]
    if not any((root / m).exists() for m in markers):
        return {}
    text = " ".join(_read(root / m) for m in markers).lower()
    py = _python_cmd(root, python)
    checks: Dict[str, str] = {}
    if "pytest" in text or (root / "tests").is_dir() or (root / "conftest.py").exists():
        checks["test"] = f"{py} -m pytest -q"
    if "ruff" in text:
        checks["lint"] = f"{py} -m ruff check ."
    if "mypy" in text:
        checks["types"] = f"{py} -m mypy ."
    return checks


def _go_checks(root: Path) -> Dict[str, str]:
    if not (root / "go.mod").is_file():
        return {}
    checks = {"test": "go test ./...", "types": "go vet ./..."}
    if (root / ".golangci.yml").exists() or (root / ".golangci.yaml").exists():
        checks["lint"] = "golangci-lint run"
    return checks


def _rust_checks(root: Path) -> Dict[str, str]:
    if not (root / "Cargo.toml").is_file():
        return {}
    return {"test": "cargo test --quiet", "lint": "cargo clippy --quiet -- -D warnings"}


def _jvm_checks(root: Path) -> Dict[str, str]:
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        if (root / "gradlew").exists() or (root / "gradlew.bat").exists():
            gradle = r"gradlew.bat" if os.name == "nt" else "./gradlew"
        else:
            gradle = "gradle"
        return {"test": f"{gradle} test --quiet"}
    if (root / "pom.xml").exists():
        mvn = ("mvnw.cmd" if os.name == "nt" else "./mvnw") if (root / "mvnw").exists() else "mvn"
        return {"test": f"{mvn} -q test"}
    return {}


def _dotnet_checks(root: Path) -> Dict[str, str]:
    if not any(root.glob("*.sln")) and not any(root.glob("*.csproj")) and not any(root.glob("*/*.csproj")):
        return {}
    return {"test": "dotnet test --nologo -v q", "lint": "dotnet format --verify-no-changes"}


def detect_checks(root: Path, python: str, full: bool = True) -> Dict[str, str]:
    """Checks for every stack found. The first stack keeps plain names; later ones get a prefix."""
    stacks = [("", _node_checks(root)), ("py_", _python_checks(root, python))]
    if full:
        stacks += [("go_", _go_checks(root)), ("rs_", _rust_checks(root)),
                   ("jvm_", _jvm_checks(root)), ("net_", _dotnet_checks(root))]
    found = [(prefix, checks) for prefix, checks in stacks if checks]
    if not found:
        return {}
    merged = dict(found[0][1])
    for prefix, checks in found[1:]:
        merged.update({f"{prefix}{k}": v for k, v in checks.items()})
    return merged


# ---------- python for the hook ----------

def find_python() -> Optional[str]:
    """A Python 3.9+ interpreter on PATH, skipping the Windows Store stub."""
    candidates = [sys.executable] + [shutil.which(n) for n in ("python3", "python", "py")]
    for exe in candidates:
        if not exe:
            continue
        try:
            out = subprocess.run([exe, "-c", "import sys; print(sys.version_info >= (3, 9))"],
                                 capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out.returncode == 0 and out.stdout.strip() == "True":
            return exe
    return None


# ---------- writing ----------

def render_config(checks: Dict[str, str], full: bool = True) -> str:
    lines = [
        "# Proof Kit: the commands that prove the agent's work.",
        "# The Stop hook runs these before the agent is allowed to finish. Edit freely.",
        "",
        "[checks]",
    ]
    if not full:
        dropped = [n for n in checks if n != "test"]
        checks = {n: c for n, c in checks.items() if n == "test"}
        lines += ["# The free edition runs the test command. Lint and type checks are in the full edition."]
        if dropped:
            lines += [f"# also detected: {', '.join(dropped)}"]
    if checks:
        lines += [f'{name} = {json.dumps(cmd)}' for name, cmd in checks.items()]
    else:
        lines += ['# No checks detected. Add at least one, for example:', '# test = "npm test --silent"']
    lines += [
        "",
        "[stop_hook]",
        "enabled = true",
        "max_attempts = 3        # after this many blocked rounds, hand back to the human",
        "only_if_changed = true  # skip when no files changed",
        "timeout_seconds = 300   # per check",
        "",
    ]
    if full:
        lines += [
            "[guards]",
            "tamper = true                # block edits that skip, delete or weaken tests",
            "allow_test_changes = false   # set true while you deliberately rewrite tests",
            "secrets = true               # block reading or editing .env, keys and credential files",
            'secrets_allow = ""           # comma-separated exceptions, e.g. "fixtures/test.pem"',
            "",
        ]
    return "\n".join(lines)


def _is_ours(hook: Dict) -> bool:
    return any("/.claude/proof-kit/proof_kit/" in str(a) for a in hook.get("args", []))


def merge_hooks(settings_path: Path, python: str, timeout: int, full: bool) -> Dict:
    """Add Proof Kit's hooks, replacing any earlier Proof Kit entries and keeping everything else."""
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    hooks = settings.setdefault("hooks", {})
    for event in ("Stop", "PostToolUse", "PreToolUse"):
        groups: List[Dict] = hooks.get(event, [])
        for group in groups:
            group["hooks"] = [h for h in group.get("hooks", []) if not _is_ours(h)]
        groups[:] = [g for g in groups if g.get("hooks")]
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    hooks.setdefault("Stop", []).append({"hooks": [{
        "type": "command", "command": python, "args": [HOOK_ARG], "timeout": timeout,
    }]})
    if full:
        for event, matcher, script in GUARDS:
            hooks.setdefault(event, []).append({"matcher": matcher, "hooks": [{
                "type": "command", "command": python, "args": [HOOK_DIR + script], "timeout": GUARD_TIMEOUT,
            }]})
    return settings


def merge_hook(settings_path: Path, python: str, timeout: int) -> Dict:
    """Stop hook only (kept for older callers)."""
    return merge_hooks(settings_path, python, timeout, full=False)


def edition() -> str:
    try:
        from proof_kit.edition import EDITION
    except ImportError:
        from .edition import EDITION  # type: ignore
    return EDITION


def ensure_gitignore(root: Path) -> bool:
    path = root / ".gitignore"
    text = _read(path)
    if any(line.strip() in (".proof", ".proof/") for line in text.splitlines()):
        return False
    with path.open("a", encoding="utf-8") as fh:
        fh.write(("" if text.endswith("\n") or not text else "\n") + "# Proof Kit run state\n.proof/\n")
    return True


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Set up Proof Kit in the current project.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root (default: current folder)")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing proof.toml")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen, change nothing")
    parser.add_argument("--ci", action="store_true", help="Also add .github/workflows/proof.yml (full edition)")
    args = parser.parse_args(argv)
    full = edition() == "full"
    if args.ci and not full:
        print("The CI workflow is part of the full edition. Continuing without it.")

    root: Path = args.root.resolve()
    python = find_python()
    if python is None:
        print("Proof Kit needs Python 3.9 or newer on PATH. Install it, then run this again.")
        return 1

    checks = detect_checks(root, "python" if os.name == "nt" else "python3", full=full)
    config_path = root / "proof.toml"
    write_config = args.force or not config_path.exists()

    print(f"Proof Kit ({edition()} edition)")
    print(f"Project: {root}")
    print(f"Python for the hook: {python}")
    print("Checks detected:" if checks else "No checks detected; edit proof.toml to add them.")
    for name, cmd in checks.items():
        print(f"  {name}: {cmd}")
    if args.dry_run:
        print("Dry run: nothing changed.")
        return 0

    if write_config:
        config_path.write_text(render_config(checks, full=full), encoding="utf-8")
        print("Wrote proof.toml")
    else:
        print("Kept existing proof.toml (use --force to overwrite)")

    dest_pkg = root / ".claude" / "proof-kit" / "proof_kit"
    if dest_pkg.resolve() != (KIT_ROOT / "proof_kit").resolve():
        shutil.copytree(KIT_ROOT / "proof_kit", dest_pkg, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    skills = sorted(p.name for p in (KIT_ROOT / "skills").iterdir() if (p / "SKILL.md").is_file())
    for name in skills:
        shutil.copytree(KIT_ROOT / "skills" / name, root / ".claude" / "skills" / name, dirs_exist_ok=True)
    print(f"Installed the hook scripts and skills ({', '.join(skills)}) into .claude/")

    settings_path = root / ".claude" / "settings.local.json"
    from proof_kit.common import load_config  # local import so this file also runs standalone

    config = load_config(root)
    per_check = int(config["stop_hook"].get("timeout_seconds", 300))
    timeout = per_check * max(1, len([c for c in config["checks"].values() if c])) + 30
    settings = merge_hooks(settings_path, python, timeout, full)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print("Added the hooks to .claude/settings.local.json: "
          + ("Stop (checks), PostToolUse (tamper guard), PreToolUse (secrets guard)" if full else "Stop (checks)"))

    if args.ci and full:
        workflow = root / ".github" / "workflows" / "proof.yml"
        if workflow.exists() and not args.force:
            print("Kept existing .github/workflows/proof.yml (use --force to overwrite)")
        else:
            workflow.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(KIT_ROOT / "ci" / "proof.yml", workflow)
            print("Added .github/workflows/proof.yml (commit it, and commit .claude/proof-kit/ too)")

    if ensure_gitignore(root):
        print("Added .proof/ to .gitignore")
    print("\nDone. Start a new Claude Code session in this project; the hook is active from its first stop.")
    return 0


if __name__ == "__main__":
    if __package__ in (None, ""):
        sys.path.insert(0, str(KIT_ROOT))
    sys.exit(main())
