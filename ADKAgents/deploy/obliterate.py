#!/usr/bin/env python3
"""Destroy all Terraform-managed GCP resources and reset local state."""

import argparse
import shutil
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from deploy.tf_run import ENV_PATH, TF_DIR, load_env, terraform

console = Console()


def write_env_value(key: str, value: str) -> None:
    lines = ENV_PATH.read_text().splitlines()
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            updated = True
            break
    if not updated:
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n")


def clean_local_state() -> None:
    for name in ("terraform.tfstate", "terraform.tfstate.backup"):
        path = TF_DIR / name
        if path.exists():
            path.unlink()
            console.print(f"  Deleted [dim]{path.name}[/dim]")

    dot_terraform = TF_DIR / ".terraform"
    if dot_terraform.exists():
        shutil.rmtree(dot_terraform)
        console.print("  Deleted [dim].terraform/[/dim]")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Skip interactive confirmation (for CI/scripting)")
    args = parser.parse_args()
    console.print()
    console.print(Panel.fit(
        Text.assemble(
            ("!! OBLITERATE", "bold bright_red"),
            ("  --  ", "dim white"),
            ("Destroy All GCP Resources", "bold white"),
        ),
        border_style="bright_red",
        padding=(0, 2),
    ))

    if not ENV_PATH.exists():
        console.print(f"[red]Error: {ENV_PATH} not found. Run `uv run setup-env` first.[/red]")
        sys.exit(1)

    dot_env = load_env(ENV_PATH)
    project_id = dot_env.get("GOOGLE_CLOUD_PROJECT", "")

    if not project_id:
        console.print("[red]Error: GOOGLE_CLOUD_PROJECT not set in .env[/red]")
        sys.exit(1)

    console.print(f"""
  This will permanently destroy all Terraform-managed resources in:

    Project : [cyan]{project_id}[/cyan]

  Resources that will be deleted:
    * Cloud Run service
    * Artifact Registry repository
    * Discovery Engine data store + search engine
    * IAM bindings

  Local files that will be removed:
    * deploy/terraform.tfstate
    * deploy/.terraform/

  .env values that will be cleared:
    * CONTAINER_IMAGE
    * VERTEX_DATA_STORE_ID

  [bold]The GCP project itself will NOT be deleted.[/bold]
""")

    if args.force:
        console.print(f"  [yellow]--force flag set. Skipping confirmation.[/yellow]")
    else:
        console.print(f"  Type the project ID [cyan]{project_id}[/cyan] to confirm: ", end="")
        try:
            confirm = input()
        except (KeyboardInterrupt, EOFError):
            console.print("\n\n  [yellow]Aborted.[/yellow]\n")
            sys.exit(0)

        if confirm.strip() != project_id:
            console.print("\n  [yellow]Aborted — project ID did not match.[/yellow]\n")
            sys.exit(0)

    console.print("\n  [bold]Destroying GCP resources...[/bold]\n")
    terraform("destroy", "-auto-approve")

    console.print("\n  [bold]Cleaning up local state...[/bold]\n")
    clean_local_state()

    write_env_value("CONTAINER_IMAGE", "")
    write_env_value("VERTEX_DATA_STORE_ID", "")
    console.print("  Cleared [dim]CONTAINER_IMAGE[/dim] and [dim]VERTEX_DATA_STORE_ID[/dim] in .env")

    console.print()
    console.print(Panel.fit(
        Text.assemble(("Done. All resources destroyed.", "bold bright_green")),
        border_style="bright_green",
        padding=(0, 2),
    ))
    console.print("""
  Run [cyan]uv run tf-deploy[/cyan] to redeploy from scratch.

""")


if __name__ == "__main__":
    main()
