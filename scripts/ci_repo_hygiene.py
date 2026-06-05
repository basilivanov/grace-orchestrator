#!/usr/bin/env python3
"""CI repo-hygiene check: no tracked artifacts, no legacy entrypoints, no prefect_grace package."""
import subprocess, sys, tomllib

errors = []

r = subprocess.run(["git", "ls-files", "agents/"], capture_output=True, text=True)
if r.stdout.strip():
    errors.append(f"tracked artifacts in agents/:\n{r.stdout[:200]}")

with open("pyproject.toml", "rb") as f:
    d = tomllib.load(f)

scripts = d.get("project", {}).get("scripts", {})
for name in ("grace", "grace-dev", "prefect-grace", "gracectl"):
    if name in scripts:
        errors.append(f"legacy entrypoint '{name}' found in pyproject.toml")

pkgs = d.get("tool", {}).get("hatch", {}).get("build", {}).get("packages", [])
if "src/prefect_grace" in pkgs:
    errors.append("src/prefect_grace in hatch packages")

if errors:
    print("FAIL: repo-hygiene")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("OK: repo-hygiene passed")
