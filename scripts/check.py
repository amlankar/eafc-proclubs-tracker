#!/usr/bin/env python3
"""Offline syntax, lint and formatting checks. No services or EA requests."""

import ast
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    for folder in ("proclubs", "scripts", "tests"):
        for path in (ROOT / folder).rglob("*.py"):
            ast.parse(path.read_text(), filename=str(path))
    for path in ROOT.rglob("*.toml"):
        if not any(part in {".venv", "node_modules", "data"} for part in path.parts):
            tomllib.loads(path.read_text())
    for path in (ROOT / "tests/fixtures").rglob("*.json"):
        json.loads(path.read_text())
    for path in (ROOT / "scripts").glob("*.sh"):
        subprocess.run(["bash", "-n", str(path)], check=True, cwd=ROOT)
        for marker, source in re.findall(
            r"<<'(PY(?:CODE)?)'\n(.*?)^\1$", path.read_text(), re.M | re.S
        ):
            ast.parse(source, filename=f"{path}:{marker}")
    subprocess.run(
        [sys.executable, "-m", "ruff", "check", "proclubs", "scripts", "tests"],
        check=True,
        cwd=ROOT,
    )
    subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "proclubs", "scripts", "tests"],
        check=True,
        cwd=ROOT,
    )
    subprocess.run(["npm", "run", "check"], check=True, cwd=ROOT)
    print("Python, JavaScript, Bash, HTML, CSS, JSON, TOML syntax checks passed.")


if __name__ == "__main__":
    main()
