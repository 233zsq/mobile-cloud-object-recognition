"""Click adapter for persistent AI review operations."""

import json
from pathlib import Path
import click
from .. import ai_review as domain


def register(app, get_db, data, categories):
    @app.cli.command("ai-review")
    @click.option("--mode", type=click.Choice(["pilot", "pending"]), default="pilot")
    @click.option("--limit", type=click.IntRange(1, 50), default=20)
    @click.option("--category", type=click.IntRange(0, 9))
    @click.option(
        "--retry-errors",
        is_flag=True,
        help="Explicitly retry failed suggestions, preserving all prior charged/reserved usage.",
    )
    @click.option(
        "--cohort",
        type=click.Path(exists=True, path_type=Path),
        help="Reuse sample IDs and unchanged human references from a pilot report.",
    )
    @click.option("--report", type=click.Path(path_type=Path))
    def run(mode, limit, category, retry_errors, cohort, report):
        """Suggest on public photos; pilot compares against hidden human decisions."""
        try:
            key = domain.read_key(app.config)
        except domain.ReviewError as error:
            raise click.ClickException(str(error)) from None
        if cohort and (mode != "pilot" or category is not None):
            raise click.UsageError("--cohort requires pilot mode without --category")
        try:
            output = domain.run_review(
                get_db(),
                data,
                categories,
                app.config,
                key,
                mode,
                limit,
                category,
                retry_errors,
                cohort,
                lambda message: click.echo(message, err=True),
            )
        except domain.ReviewError as error:
            raise click.ClickException(str(error)) from None
        if report:
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(
                json.dumps(output, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        click.echo(
            json.dumps(
                {k: v for k, v in output.items() if k != "samples"}, ensure_ascii=False
            )
        )
        if output["count"] < output["requested_count"] or any(
            r["state"] != "done" for r in output["samples"]
        ):
            raise click.ClickException(
                "AI run incomplete; inspect safe error_code in ai_reviews"
            )
