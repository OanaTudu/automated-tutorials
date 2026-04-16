#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT

"""CLI entry point for the tutorial automation pipeline."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_ERROR = 2


def configure_logging(verbose: bool = False) -> None:
    """Configure root logger with level and format."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


@click.command()
@click.argument("topic")
@click.option(
    "-c",
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to the pipeline YAML config file.",
)
@click.option(
    "-a",
    "--audience",
    default="data scientists",
    show_default=True,
    help="Target audience for the tutorial.",
)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.pass_context
def main(
    ctx: click.Context,
    topic: str,
    config_path: Path | None,
    audience: str,
    verbose: bool,
) -> None:
    """Generate a tutorial video for TOPIC."""
    configure_logging(verbose)
    try:
        from src.make_tutorial import make_tutorial

        output = make_tutorial(topic, config_path, audience=audience)
        click.echo(f"Tutorial saved: {output}")
        ctx.exit(EXIT_SUCCESS)
    except KeyboardInterrupt:
        click.echo("\nInterrupted by user", err=True)
        ctx.exit(130)
    except ValueError as exc:
        click.echo(f"Validation error: {exc}", err=True)
        ctx.exit(EXIT_ERROR)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Error: {exc}", err=True)
        ctx.exit(EXIT_FAILURE)


if __name__ == "__main__":
    sys.exit(main())
