#!/usr/bin/env python3
"""Interactive setup script to generate bank_agent/.env from user input."""

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.text import Text

console = Console()
ENV_PATH = Path(__file__).parent / "bank_agent" / ".env"

questions = [
    {
        "key": "GOOGLE_API_KEY",
        "prompt": "Gemini API key",
        "hint": "Get one at https://aistudio.google.com/apikey",
        "color": "magenta",
    },
    {
        "key": "GOOGLE_CLOUD_PROJECT",
        "prompt": "Google Cloud Project ID",
        "color": "cyan",
    },
    {
        "key": "GOOGLE_CLOUD_LOCATION",
        "prompt": "Google Cloud Location",
        "default": "global",
        "color": "cyan",
    },
    {
        "key": "WEBSITE_DOMAIN",
        "prompt": "Website domain to crawl for vector search",
        "hint": "e.g. www.example.com  (used by Terraform to build the data store)",
        "color": "cyan",
    },
    {
        "key": "VERTEX_DATA_STORE_ID",
        "prompt": "Vertex AI Data Store ID",
        "hint": "Leave blank for now — run `uv run tf-deploy` first, then re-run setup-env with the output value",
        "default": "",
        "color": "cyan",
    },
    {
        "key": "BQ_DATASET",
        "prompt": "BigQuery dataset ID",
        "default": "",
        "hint": "BigQuery dataset containing customers/accounts/transactions tables (leave blank to use local SQLite)",
        "color": "cyan",
    },
    {
        "key": "MEMBER_EMAIL",
        "prompt": "IAM member for Terraform",
        "hint": "e.g. user:you@example.com or serviceAccount:sa@project.iam.gserviceaccount.com",
        "default": "",
        "color": "yellow",
    },
    {
        "key": "CONTAINER_IMAGE",
        "prompt": "Container image for Cloud Run (leave blank to skip)",
        "hint": "e.g. us-central1-docker.pkg.dev/PROJECT/REPO/agent:latest",
        "default": "",
        "color": "yellow",
    },
]


def main():
    console.print()
    console.print(Panel.fit(
        Text.assemble(
            ("Bank Agent", "bold bright_green"),
            (" — ", "dim white"),
            ("Environment Setup", "bold white"),
        ),
        border_style="bright_green",
        padding=(0, 2),
    ))
    console.print()

    if ENV_PATH.exists():
        if not Confirm.ask(
            f"[yellow]  .env already exists[/yellow] at [dim]{ENV_PATH}[/dim]. Overwrite?",
            default=False,
        ):
            console.print("\n[red]  Aborted.[/red]\n")
            return

    console.print(Rule("[dim]Configuration[/dim]", style="dim"))
    console.print()

    values = {}
    for q in questions:
        color = q.get("color", "white")
        if "hint" in q:
            console.print(f"  [dim]{q['hint']}[/dim]")
        values[q["key"]] = Prompt.ask(
            f"  [{color}]{q['prompt']}[/{color}]",
            default=q.get("default", ""),
        )
        console.print()

    console.print(Rule(style="dim"))
    console.print()

    lines = [f"{key}={value}\n" for key, value in values.items()]
    ENV_PATH.write_text("".join(lines))

    console.print(Panel.fit(
        Text.assemble(
            ("Done! ", "bold bright_green"),
            (".env written to ", "white"),
            (str(ENV_PATH), "dim"),
        ),
        border_style="bright_green",
        padding=(0, 2),
    ))
    console.print()


if __name__ == "__main__":
    main()
