import ipaddress
from pathlib import Path
from typing import Optional

import typer
from requests.auth import HTTPDigestAuth

from cctv.config import ConfigError, load_config
from cctv import executor, reporter, scanner

app = typer.Typer()


def _validate_subnet(value: Optional[str]) -> Optional[str]:
    if value is not None:
        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError:
            raise typer.BadParameter(f"'{value}' is not a valid CIDR notation")
    return value


@app.command(name="list")
def list_cameras(
    config: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to cameras.yaml config file",
    ),
    subnet: Optional[str] = typer.Option(
        None, "--subnet", help="Override subnet (CIDR)", callback=_validate_subnet
    ),
) -> None:
    """Discover Axis cameras on the subnet."""
    try:
        cfg = load_config(config)
    except ConfigError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    auth = HTTPDigestAuth(cfg.username, cfg.password)
    effective_subnet = subnet or cfg.subnet
    cameras = scanner.scan(effective_subnet, auth, cfg.timeout)
    reporter.print_camera_list(cameras)
    if not cameras:
        raise typer.Exit(code=2)


@app.command()
def apply(
    config: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to cameras.yaml config file",
    ),
    subnet: Optional[str] = typer.Option(
        None, "--subnet", help="Override subnet (CIDR)", callback=_validate_subnet
    ),
) -> None:
    """Apply config to all discovered cameras."""
    try:
        cfg = load_config(config)
    except ConfigError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    auth = HTTPDigestAuth(cfg.username, cfg.password)
    effective_subnet = subnet or cfg.subnet
    cameras = scanner.scan(effective_subnet, auth, cfg.timeout)
    results = executor.apply_all(cameras, cfg, auth)
    exit_code = reporter.print_apply_results(results)
    raise typer.Exit(code=exit_code)


if __name__ == "__main__":
    app()
