#!/usr/bin/env python3
"""Deploy all BigQuery datasets defined in datasets/*.yaml."""

import datetime
import re
import sys
from pathlib import Path

import yaml
from google.cloud import bigquery
from google.cloud.exceptions import Conflict
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from deploy.tf_run import ENV_PATH, load_env

console = Console()

REPO_ROOT = Path(__file__).parent.parent
DATASETS_DIR = REPO_ROOT / "datasets"


def interpolate(value: str, env: dict[str, str]) -> str:
    """Resolve ${VAR} tokens in value using env dict."""
    def replacer(match: re.Match) -> str:
        var = match.group(1)
        if var not in env:
            raise ValueError(f"Env var '{var}' referenced in dataset YAML but not set in .env")
        return env[var]
    return re.sub(r"\$\{([^}]+)\}", replacer, value)


def load_dataset_configs(env: dict[str, str]) -> list[dict]:
    configs = []
    for yaml_file in sorted(DATASETS_DIR.glob("*.yaml")):
        with yaml_file.open() as f:
            cfg = yaml.safe_load(f)
        cfg["dataset"] = interpolate(cfg["dataset"], env)
        cfg.setdefault("location", "US")
        for table in cfg.get("tables", []):
            if "seed_file" in table and "seed_data" in table:
                raise ValueError(
                    f"Table '{table['name']}' in {yaml_file.name} has both "
                    "seed_file and seed_data — use one only"
                )
        configs.append(cfg)
    return configs


def schema_from_config(fields: list[dict]) -> list[bigquery.SchemaField]:
    return [
        bigquery.SchemaField(f["name"], f["type"], mode=f.get("mode", "NULLABLE"))
        for f in fields
    ]


def normalize_seed_rows(rows: list[dict]) -> list[dict]:
    """Convert date/datetime objects PyYAML auto-parses back to ISO strings."""
    result = []
    for row in rows:
        result.append({
            k: v.isoformat() if isinstance(v, (datetime.date, datetime.datetime)) else v
            for k, v in row.items()
        })
    return result


def create_dataset(client: bigquery.Client, dataset_id: str, project: str, location: str = "US") -> None:
    full_id = f"{project}.{dataset_id}"
    dataset = bigquery.Dataset(full_id)
    dataset.location = location
    try:
        client.create_dataset(dataset)
        console.print(f"  Created dataset [cyan]{full_id}[/cyan]")
    except Conflict:
        console.print(f"  Dataset [cyan]{full_id}[/cyan] already exists — skipping create")


def create_table(client: bigquery.Client, project: str, dataset_id: str, table_name: str, schema_fields: list[dict]) -> None:
    table_ref = f"{project}.{dataset_id}.{table_name}"
    table = bigquery.Table(table_ref, schema=schema_from_config(schema_fields))
    try:
        client.create_table(table)
        console.print(f"  Created table   [cyan]{table_name}[/cyan]")
    except Conflict:
        console.print(f"  Table [cyan]{table_name}[/cyan] already exists — skipping create")


def load_from_file(client: bigquery.Client, project: str, dataset_id: str, table_name: str, schema_fields: list[dict], seed_path: Path) -> int:
    table_ref = f"{project}.{dataset_id}.{table_name}"
    job_config = bigquery.LoadJobConfig(
        schema=schema_from_config(schema_fields),
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    with seed_path.open("rb") as f:
        job = client.load_table_from_file(f, table_ref, job_config=job_config)
    job.result()
    table = client.get_table(table_ref)
    console.print(f"  Loaded  [cyan]{table_name}[/cyan] — [bold]{table.num_rows}[/bold] rows")
    return table.num_rows


def load_from_inline(client: bigquery.Client, project: str, dataset_id: str, table_name: str, schema_fields: list[dict], rows: list[dict]) -> int:
    table_ref = f"{project}.{dataset_id}.{table_name}"
    job_config = bigquery.LoadJobConfig(
        schema=schema_from_config(schema_fields),
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = client.load_table_from_json(normalize_seed_rows(rows), table_ref, job_config=job_config)
    job.result()
    table = client.get_table(table_ref)
    console.print(f"  Loaded  [cyan]{table_name}[/cyan] — [bold]{table.num_rows}[/bold] rows")
    return table.num_rows


def main() -> None:
    console.print()
    console.print(Panel.fit(
        Text.assemble(
            ("BigQuery Deploy", "bold bright_green"),
        ),
        border_style="bright_green",
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

    if not DATASETS_DIR.exists():
        console.print(f"[red]Error: {DATASETS_DIR} not found. No datasets to deploy.[/red]")
        sys.exit(1)

    try:
        configs = load_dataset_configs(dot_env)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    if not configs:
        console.print("[yellow]No *.yaml files found in datasets/ — nothing to deploy.[/yellow]")
        return

    console.print(f"\n  Project  : [cyan]{project}[/cyan]")
    console.print(f"  Datasets : [cyan]{', '.join(c['dataset'] for c in configs)}[/cyan]\n")

    client = bigquery.Client(project=project)
    grand_total = 0

    for i, cfg in enumerate(configs, start=1):
        dataset_id = cfg["dataset"]
        tables = cfg.get("tables", [])

        console.print(f"  [bold]Step {i}:[/bold] [cyan]{dataset_id}[/cyan]")

        create_dataset(client, dataset_id, project, cfg["location"])

        for table_cfg in tables:
            create_table(client, project, dataset_id, table_cfg["name"], table_cfg["schema"])

        for table_cfg in tables:
            table_name = table_cfg["name"]
            schema_fields = table_cfg["schema"]

            if "seed_file" in table_cfg:
                seed_path = REPO_ROOT / table_cfg["seed_file"]
                if not seed_path.exists():
                    console.print(f"  [yellow]seed_file {seed_path} not found — skipping {table_name}[/yellow]")
                    continue
                grand_total += load_from_file(client, project, dataset_id, table_name, schema_fields, seed_path)
            elif "seed_data" in table_cfg:
                grand_total += load_from_inline(client, project, dataset_id, table_name, schema_fields, table_cfg["seed_data"])
            else:
                console.print(f"  [dim]No seed data for {table_name}[/dim]")

        console.print()

    console.print(Panel.fit(
        Text.assemble(
            ("Done! ", "bold bright_green"),
            (f"{grand_total} rows loaded across all datasets", "white"),
        ),
        border_style="bright_green",
        padding=(0, 2),
    ))
    console.print()


if __name__ == "__main__":
    main()
