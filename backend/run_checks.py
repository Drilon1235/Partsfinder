"""Runs the environment check, the tests and (optionally) the test data generator.

Everything is shown and also written to backend/check_log.txt (UTF-8),
so the result can be read afterwards.

Usage:  python run_checks.py [--testdata] [--import] [--eval]
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
LOG = HERE / "check_log.txt"
ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
       "TRANSFORMERS_VERBOSITY": "error", "HF_HUB_DISABLE_PROGRESS_BARS": "1"}


def run(title: str, args: list[str], cwd: Path) -> int:
    proc = subprocess.run([sys.executable, *args], cwd=cwd, env=ENV, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    block = f"\n=== {title} (exit code {proc.returncode}) ===\n{proc.stdout}{proc.stderr}"
    print(block, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(block)
    return proc.returncode


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    LOG.write_text(f"Check started {datetime.now():%Y-%m-%d %H:%M:%S} with Python {sys.version.split()[0]}\n",
                   encoding="utf-8")
    env_ok = run("Environment check", ["check_env.py"], HERE) == 0
    tests_ok = run("Tests", ["-m", "pytest", "-q"], HERE) == 0
    data_ok = True
    if "--testdata" in sys.argv:
        if env_ok:
            data_ok = run("Generate test data", ["scripts/generate_testdata.py", "--clean"], PROJECT) == 0
        else:
            msg = "\nTest data skipped: first fix the ERROR lines in the environment check.\n"
            print(msg)
            with LOG.open("a", encoding="utf-8") as f:
                f.write(msg)
            data_ok = False
    import_ok = True
    if "--import" in sys.argv:
        if env_ok and data_ok:
            print("\nImporting test data into the database. The first time the AI model for"
                  " embeddings is downloaded (~470 MB), which can take a few minutes...", flush=True)
            import_ok = run("Import test data", ["-m", "partsfinder.ingest", "--testdata", "--no-ai"], HERE) == 0
        else:
            import_ok = False
    eval_ok = True
    if "--eval" in sys.argv:
        eval_ok = import_ok and run("Search engine evaluation", ["eval_search.py"], HERE) == 0
    summary = (f"\nSummary: environment {'OK' if env_ok else 'ERROR'}, tests {'OK' if tests_ok else 'ERROR'}"
               + (f", test data {'OK' if data_ok else 'ERROR'}" if "--testdata" in sys.argv else "")
               + (f", import {'OK' if import_ok else 'ERROR'}" if "--import" in sys.argv else "")
               + (f", search evaluation {'OK' if eval_ok else 'ERROR'}" if "--eval" in sys.argv else "") + "\n")
    print(summary)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(summary)
    return 0 if (env_ok and tests_ok and data_ok and import_ok and eval_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
