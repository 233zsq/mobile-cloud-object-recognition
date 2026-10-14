"""Local administrative commands; no training or remote collection."""

import json
from pathlib import Path
import click
from ..context import resources
from ..database import db
from ..services.public_queue import PublicQueueError, import_queue
from ..services.accounts import BootstrapError, bootstrap_invitation
from ..services.candidates import (
    CandidateError,
    register_candidate as register_comparison,
)
from ..utils import encode


def register(app):
    @app.cli.command("bootstrap")
    def bootstrap():
        """Create an initial admin invitation, never a hardcoded password."""
        try:
            token = bootstrap_invitation(db())
        except BootstrapError as error:
            raise click.ClickException(str(error)) from None
        click.echo("/join/" + token)

    @app.cli.command("import-public")
    @click.argument("archive_file", type=click.Path(exists=True, path_type=Path))
    @click.option("--report", type=click.Path(path_type=Path))
    def import_public(archive_file, report):
        """Import bounded local candidates as pending photos."""
        runtime = resources()
        try:
            summary = import_queue(
                db(),
                runtime.data,
                runtime.queue_category_hashes,
                archive_file,
                click.echo,
            )
        except PublicQueueError as error:
            raise click.ClickException(str(error)) from None
        if report:
            report.write_bytes(encode(summary))
        click.echo(json.dumps(summary, ensure_ascii=False))

    @app.cli.command("register-candidate")
    @click.argument("report_file", type=click.Path(exists=True, path_type=Path))
    def register_candidate(report_file):
        """Register an immutable comparison; never execute training."""
        try:
            version = register_comparison(db(), resources().baseline, report_file)
        except CandidateError as error:
            raise click.ClickException(str(error)) from None
        if version:
            click.echo("Registered pending candidate " + version)
