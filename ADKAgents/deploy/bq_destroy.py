#!/usr/bin/env python3
"""Delete all BigQuery datasets defined in datasets/*.yaml."""

import sys

from google.cloud.exceptions import NotFound
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from deploy.bq_deploy import load_dataset_configs
from deploy.tf_run import ENV_PATH, load_env

console = Console()


def main() -> None:
    console.print()
    console.print(Panel.fit(
        Text.assemble(
            ("BigQuery Destroy", "bold bright_red"),
        ),
        border_style="bright_red",
        padding=(0, 2),
    ))

    if not ENV_PATH.exists():
        console.print(f"[red]Error: {ENV_PATH} not found. Run `uv run setup-env` first.[/red]")
        sys.exit(1)

    dot_env = load_env(ENV_PATH)
    project = dot_env.get("GOOGLE_CLOUD_PROJECT", "")
    if not project:
        console.print("[red]Error: GOOGLE_CLOUD_PROJECT not set in .env[/red]")
        sys.exit(1)

    try:
        configs = load_dataset_configs(dot_env)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    if not configs:
        console.print("[yellow]No *.yaml files found in datasets/ — nothing to destroy.[/yellow]")
        return

    dataset_ids = [c["dataset"] for c in configs]
    console.print(f"\n  Project  : [cyan]{project}[/cyan]")
    console.print(f"  Datasets : [cyan]{', '.join(dataset_ids)}[/cyan]\n")

    from google.cloud import bigquery
    client = bigquery.Client(project=project)

    for dataset_id in dataset_ids:
        full_id = f"{project}.{dataset_id}"
        try:
            client.delete_dataset(full_id, delete_contents=True, not_found_ok=False)
            console.print(f"  Deleted [cyan]{full_id}[/cyan]")
        except NotFound:
            console.print(f"  [dim]{full_id} not found — skipping[/dim]")

    console.print()
    console.print(Panel.fit(
        Text.assemble(("Done. All datasets deleted.", "bold bright_green")),
        border_style="bright_green",
        padding=(0, 2),
    ))
    console.print()


if __name__ == "__main__":
    main()
