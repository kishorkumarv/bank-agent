#!/usr/bin/env python3
"""Terraform wrapper — loads all bank_agent/.env vars as TF_VAR_* then runs terraform."""

import os
import subprocess
import sys
from pathlib import Path

ENV_PATH = Path(__file__).parent.parent / "bank_agent" / ".env"
TF_DIR = Path(__file__).parent


def load_env(path: Path) -> dict[str, str]:
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def build_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        print(f"Error: {ENV_PATH} not found. Run `uv run setup-env` first.", file=sys.stderr)
        sys.exit(1)
    dot_env = load_env(ENV_PATH)
    env = {**os.environ}
    for key, value in dot_env.items():
        env[f"TF_VAR_{key}"] = value
    env["TF_VAR_project_id"] = dot_env.get("GOOGLE_CLOUD_PROJECT", "")
    env["TF_VAR_website_domain"] = dot_env.get("WEBSITE_DOMAIN", "")
    env["TF_VAR_member_email"] = dot_env.get("MEMBER_EMAIL", "")
    env["TF_VAR_google_api_key"] = dot_env.get("GOOGLE_API_KEY", "")
    env["TF_VAR_container_image"] = dot_env.get("CONTAINER_IMAGE", "")
    env["TF_VAR_data_store_id"] = dot_env.get("DATA_STORE_ID", "website-ds")
    env["TF_VAR_bq_dataset"] = dot_env.get("BQ_DATASET", "")
    return env


def terraform(*args: str) -> None:
    result = subprocess.run(["terraform", *args], cwd=TF_DIR, env=build_env())
    if result.returncode != 0:
        sys.exit(result.returncode)


def main():
    result = subprocess.run(["terraform", *sys.argv[1:]], cwd=TF_DIR, env=build_env())
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
