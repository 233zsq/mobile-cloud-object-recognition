"""Click adapter for persistent AI review operations."""

import json
import re
from pathlib import Path
import click
from .. import ai_triage as domain
from ..services.triage_rounds import RoundError, run_round


def register(app, get_db, data, categories):
    @app.cli.command("ai-triage-round")
    @click.option("--actor", type=int, required=True)
    @click.option(
        "--archive", type=click.Path(exists=True, path_type=Path), required=True
    )
    @click.option("--max-photos", type=click.IntRange(1, 2000), default=500)
    @click.option("--progress", type=click.Path(path_type=Path), required=True)
    def triage_round(actor, archive, max_photos, progress):
        """One finite, explicitly scoped round; each job remains <=50 photos."""
        try:
            result = run_round(
                get_db(),
                data,
                categories,
                app.config,
                actor,
                archive,
                max_photos,
                progress,
            )
        except RoundError as error:
            raise click.ClickException(str(error)) from None
        click.echo(json.dumps(result, ensure_ascii=False))
        if result["state"] == "stopped":
            raise click.ClickException("round_stopped_" + result["error_code"])

    @app.cli.command("ai-triage-worker")
    @click.option("--job", required=True)
    def worker(job):
        if not re.fullmatch("[0-9a-f]{32}", job):
            raise click.ClickException("invalid_job_id")
        report = domain.run_job(get_db(), data, categories, app.config, job)
        click.echo(
            json.dumps(
                {key: value for key, value in report.items() if key != "samples"},
                ensure_ascii=False,
            )
        )
        if report["state"] != "done":
            raise click.ClickException("triage_" + report["error_code"])

    @app.cli.command("ai-triage")
    @click.option("--actor", type=int, required=True)
    @click.option("--limit", type=click.IntRange(1, 50), default=20)
    @click.option("--apply", "apply_changes", is_flag=True)
    def triage(actor, limit, apply_changes):
        identity = domain.new_job(get_db(), actor, limit, app.config, apply_changes)
        report = domain.run_job(get_db(), data, categories, app.config, identity)
        click.echo(
            json.dumps(
                {key: value for key, value in report.items() if key != "samples"},
                ensure_ascii=False,
            )
        )
        if report["state"] != "done":
            raise click.ClickException("triage_" + report["error_code"])

    @app.cli.command("ai-triage-policy")
    @click.option("--actor", type=int, required=True)
    @click.option("--enabled", "value", type=bool, required=True)
    def policy(actor, value):
        active = domain.policy_for(domain.configured_profiles(app.config))
        domain.set_enabled(get_db(), actor, value, active)
        click.echo(json.dumps({"enabled": value, "policy": active}))
