import argparse
import logging
import os
import subprocess
from importlib.metadata import PackageNotFoundError, version

import argcomplete
import yaml
from rich.console import Console
from rich.table import Table
from rich.text import Text

from cli import experiment
from cli.auth.auth_utils import get_machine_id
from cli.auth.credential_store import create_credential_store
from cli.auth.session_manager import create_session_manager
from cli.completers import config_file_completer, experiment_completer
from cli.config import load_config
from cli.http_client import HttpClient, create_http_client
from cli.utils.config_paths import get_config_dir, get_config_path
from cli.utils.url_utils import get_api_endpoint

logger = logging.getLogger("hivekit")

try:
    __version__ = version("hivekit")
except PackageNotFoundError:
    __version__ = "unknown"


def init(args) -> None:
    """Initialize a default Hive configuration."""

    console = Console()

    BLUE = "\033[94m"
    RESET = "\033[0m"

    ascii_art = r"""
 ███          █████   █████  ███                       █████   ████  ███   █████
░░░███       ░░███   ░░███  ░░░                       ░░███   ███░  ░░░   ░░███
  ░░░███      ░███    ░███  ████  █████ █████  ██████  ░███  ███    ████  ███████
    ░░░███    ░███████████ ░░███ ░░███ ░░███  ███░░███ ░███████    ░░███ ░░░███░
     ███░     ░███░░░░░███  ░███  ░███  ░███ ░███████  ░███░░███    ░███   ░███
   ███░       ░███    ░███  ░███  ░░███ ███  ░███░░░   ░███ ░░███   ░███   ░███ ███
 ███░         █████   █████ █████  ░░█████   ░░██████  █████ ░░████ █████  ░░█████
░░░          ░░░░░   ░░░░░ ░░░░░    ░░░░░     ░░░░░░  ░░░░░   ░░░░ ░░░░░    ░░░░░
    """

    print(f"{BLUE}{ascii_art}{RESET}")

    # Default config path
    config_dir = get_config_dir()
    config_path = get_config_path()

    # Check if config already exists
    if os.path.exists(config_path):
        msg = Text("Configuration file already exists at ", style="yellow")
        msg.append(config_path, style="bold yellow")
        console.print(msg)

        # Ask user if they want to overwrite
        response = input("Do you want to overwrite it? (y/N): ").strip().lower()
        if response not in ["y", "yes"]:
            console.print("Initialization cancelled.", style="bold red")
            return

    # Create config directory if it doesn't exist
    os.makedirs(config_dir, exist_ok=True)

    # Prompt for organization ID
    organization_id = input("Enter your organization ID: ").strip()
    if not organization_id:
        console.print("[bold red]Error:[/bold red] Organization ID is required.")
        return

    # Default configuration template
    # Use yaml.safe_dump to properly quote the organization_id to prevent YAML injection
    safe_organization_id = yaml.safe_dump(organization_id, default_style="'").strip()
    default_config = f"""# Hive Configuration File
# This file contains the configuration for your Hive experiments.

# Uncomment and configure the following fields as needed:

organization_id: {safe_organization_id}

log_level: INFO

repo:
  source: https://github.com/your-org/your-repo.git
  branch: main
  evaluation_script: evaluator.py
  evolve_files_and_ranges: main.py
  # include_files_and_ranges: file.py:1-10

runtime:
  num_agents: 1
  max_runtime_seconds: -1  # -1 means no limit
  max_iterations: -1  # -1 means no limit

sandbox:
  base_image: python:3.9-slim
  timeout: 60
  resources:
    cpu: "1"
    memory: "2Gi"
    # shmsize: "1Gi"
    # accelerators: a100-80gb:8
  setup_script: |
    pip install -r requirements.txt
  # envs:
  #   - name: EXAMPLE_VAR
  #     value: example_value

# prompt:
#   context: "Additional context for your experiment"
#   ideas:
#     - "Idea 1"
#     - "Idea 2"
#   enable_evolution: false
"""

    # Write the default configuration
    with open(config_path, "w") as f:
        f.write(default_config)

    msg = Text("✓ Initialized Hive configuration at ", style="bold green")
    msg.append(config_path, style="bold magenta")
    console.print(msg)
    console.print("\nEdit the configuration with:", style="dim")
    console.print("  hive edit config", style="bold cyan")


def login(args) -> None:
    """Log in to the Hive platform via OIDC."""
    console = Console()

    try:
        organization_id = _load_organization_id()
        insecure = getattr(args, "insecure", False)
        _run_login(console=console, organization_id=organization_id, insecure=insecure)
    except Exception as e:
        console.print(f"[bold red]✗ Login failed:[/bold red] {e}")


def logout(args) -> None:
    """
    Log out by clearing stored credentials for the currently configured organization.
    """
    console = Console()

    try:
        organization_id = _load_organization_id()
        credential_store = create_credential_store(
            clients_dir=os.path.join(get_config_dir(), "clients"),
            machine_id_func=get_machine_id,
        )
        credential_store.delete_token(organization_id=organization_id)
        console.print(
            f"[bold green]✓ Cleared credentials for organization '{organization_id}'.[/bold green]"
        )
    except Exception as e:
        console.print(f"[bold red]✗ Logout failed:[/bold red] {e}")


def edit_cli(args):
    editor = os.environ.get("EDITOR", "vim")
    subprocess.run([editor, args.config])

    console = Console()
    msg = Text(args.config, style="bold magenta")
    msg.append(" edited successfully.", style="bold green")
    console.print(msg)


def create_experiment(args) -> None:
    """Create an experiment based on the config."""
    console = Console()

    # Load configuration
    try:
        config = load_config(args.config)
    except Exception as e:
        console.print(f"[bold red]Error loading config:[/bold red] {e}")
        return

    # Generate experiment name
    try:
        experiment_name = experiment.generate_experiment_name(args.name)
    except Exception as e:
        console.print(f"[bold red]Error generating experiment name:[/bold red] {e}")
        return

    console.print(f"[bold cyan]Creating experiment:[/bold cyan] {experiment_name}")

    # Build experiment CRD from config
    try:
        experiment_crd = experiment.build_experiment_crd(config, experiment_name)
    except Exception as e:
        console.print(f"[bold red]Error building experiment CRD:[/bold red] {e}")
        return

    try:
        client = _get_http_client(args)
        _ = client.create_experiment(experiment_crd)
        console.print(f"[bold green]✓ Experiment '{experiment_name}' created successfully![/bold green]")

    except Exception as e:
        console.print(f"[bold red]✗ Failed to create experiment:[/bold red] {e}")
        console.print("[yellow]Troubleshooting tips:[/yellow]")
        console.print("  • Ensure HIVE_API_ENDPOINT is set correctly")
        return


def delete_experiments(args) -> None:
    """Delete one or more experiments."""
    console = Console()

    experiment_names = args.name if isinstance(args.name, list) else [args.name]

    if len(experiment_names) == 1:
        console.print(f"[bold yellow]Deleting experiment:[/bold yellow] {experiment_names[0]}")
    else:
        console.print(f"[bold yellow]Deleting {len(experiment_names)} experiments:[/bold yellow]")
        for name in experiment_names:
            console.print(f"  • {name}")

    # Confirm deletion for batch operations unless -y flag is set
    # Single experiment deletions don't require confirmation
    if len(experiment_names) > 1 and not args.yes:
        prompt = f"Are you sure you want to delete these {len(experiment_names)} experiments? (y/N): "
        response = input(prompt).strip().lower()
        if response not in ["y", "yes"]:
            console.print("[yellow]Deletion cancelled.[/yellow]")
            return

    try:
        client = _get_http_client(args)

        if len(experiment_names) == 1:
            # Single experiment deletion
            _ = client.delete_experiment(experiment_names[0])
            console.print(f"[bold green]✓ Experiment '{experiment_names[0]}' deleted successfully![/bold green]")
        else:
            # Batch deletion
            results = client.delete_experiments_batch(experiment_names)

            # Display results
            success_count = 0
            failure_count = 0

            for name, result in results.items():
                if result["success"]:
                    console.print(f"[bold green]✓[/bold green] {name} - deleted successfully")
                    success_count += 1
                else:
                    console.print(f"[bold red]✗[/bold red] {name} - {result['error']}")
                    failure_count += 1

            # Summary
            if failure_count == 0:
                console.print(f"[bold green]All {success_count} experiments deleted successfully![/bold green]")
            else:
                console.print(f"[yellow]Completed with {success_count} successes and {failure_count} failures.[/yellow]")

    except Exception as e:
        console.print(f"[bold red]✗ Failed to delete experiment:[/bold red] {e}")
        console.print("[yellow]Troubleshooting tips:[/yellow]")
        console.print("  • Ensure HIVE_API_ENDPOINT is set correctly")
        if len(experiment_names) == 1:
            console.print(f"  • Verify the experiment '{experiment_names[0]}' exists")
        return


def list_experiments(args) -> None:
    """List all experiments."""
    console = Console()

    try:
        client = _get_http_client(args)
        result = client.list_experiments()
        experiments = result.get("experiments", [])

        if not experiments:
            console.print("[yellow]No experiments found.[/yellow]")
            return

        # Create a table to display experiments
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Agents", justify="right")
        table.add_column("Status", style="yellow")
        table.add_column("Created", style="dim")

        for exp in experiments:
            metadata = exp.get("metadata", {})
            spec = exp.get("spec", {})
            status = exp.get("status", {})

            name = metadata.get("name", "N/A")
            num_agents = spec.get("runtime", {}).get("numAgents", "N/A")
            phase = status.get("phase", "Unknown")
            created = metadata.get("creationTimestamp", "N/A")

            table.add_row(name, str(num_agents), phase, created)

        console.print(table)
        console.print(f"[dim]Total experiments:[/dim] {len(experiments)}")

    except Exception as e:
        console.print(f"[bold red]✗ Failed to list experiments:[/bold red] {e}")
        console.print("[yellow]Troubleshooting tips:[/yellow]")
        console.print("  • Ensure HIVE_API_ENDPOINT is set correctly")
        return


def get_experiment(args) -> None:
    """Get details of a specific experiment."""
    console = Console()

    experiment_name = args.name

    console.print(f"[bold cyan]Getting experiment:[/bold cyan] {experiment_name}")

    try:
        client = _get_http_client(args)
        exp = client.get_experiment(experiment_name)

        metadata = exp.get("metadata", {})
        spec = exp.get("spec", {})
        status = exp.get("status", {})

        # Display metadata
        console.print("[bold magenta]Metadata:[/bold magenta]")
        console.print(f"  [cyan]Name:[/cyan] {metadata.get('name', 'N/A')}")
        console.print(f"  [cyan]UID:[/cyan] {metadata.get('uid', 'N/A')}")
        console.print(f"  [cyan]Created:[/cyan] {metadata.get('creationTimestamp', 'N/A')}")

        # Display labels if present
        if metadata.get("labels"):
            console.print("  [cyan]Labels:[/cyan]")
            for key, value in metadata["labels"].items():
                console.print(f"    {key}: {value}")

        # Display spec
        console.print("[bold magenta]Spec:[/bold magenta]")
        runtime = spec.get("runtime", {})
        console.print("  [cyan]Runtime:[/cyan]")
        console.print(f"    Agents: {runtime.get('numAgents', 'N/A')}")
        console.print(f"    Max Runtime: {runtime.get('maxRuntimeSeconds', 'N/A')}s")
        console.print(f"    Max Iterations: {runtime.get('maxIterations', 'N/A')}")

        repo = spec.get("repo", {})
        console.print("  [cyan]Repository:[/cyan]")
        console.print(f"    Source: {repo.get('source', 'N/A')}")
        console.print(f"    Branch: {repo.get('branch', 'N/A')}")
        console.print(f"    Evaluation Script: {repo.get('evaluationScript', 'N/A')}")

        sandbox = spec.get("sandbox", {})
        console.print("  [cyan]Sandbox:[/cyan]")
        console.print(f"    Timeout: {sandbox.get('timeout', 'N/A')}s")
        resources = sandbox.get("resources", {})
        if resources:
            console.print("    Resources:")
            console.print(f"      CPU: {resources.get('cpu', 'N/A')}")
            console.print(f"      Memory: {resources.get('memory', 'N/A')}")

        # Display status
        console.print("[bold magenta]Status:[/bold magenta]")
        console.print(f"  [cyan]Phase:[/cyan] {status.get('phase', 'Unknown')}")

    except Exception as e:
        console.print(f"[bold red]✗ Failed to get experiment:[/bold red] {e}")
        console.print("[yellow]Troubleshooting tips:[/yellow]")
        console.print("  • Ensure HIVE_API_ENDPOINT is set correctly")
        console.print(f"  • Verify the experiment '{experiment_name}' exists")
        return


def _get_http_client(args: argparse.Namespace) -> HttpClient:
    """
    Build an HttpClient from the parsed command-line arguments.

    Reads the organization ID from the config file when authentication is
    enabled.
    """
    return create_http_client(
        organization_id=_load_organization_id(),
        no_auth=getattr(args, "no_auth", False),
        insecure=getattr(args, "insecure", False),
    )


def _load_organization_id() -> str:
    """
    Load the organization ID from the config file.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the config file does not contain an organization ID.
    """
    config_path = get_config_path()
    if not os.path.exists(config_path):
        raise FileNotFoundError("No configuration found. Please run 'hive init' first.")

    config = load_config(file_path=config_path)

    if not config.organization_id:
        raise ValueError("No organization_id found in config. Please run 'hive init' to set it.")

    return config.organization_id


def _run_login(console: Console, organization_id: str, insecure: bool = False) -> None:
    """
    Run the OIDC login flow for the given organization.
    """
    session_manager = create_session_manager(
        organization_id=organization_id,
        base_url=get_api_endpoint(),
        insecure=insecure,
    )
    console.print("[yellow]Opening browser for login...[/yellow]")
    try:
        session_manager.login()
        console.print("[bold green]✓ Login successful![/bold green]")
    except Exception as e:
        console.print(f"[bold red]✗ Login failed:[/bold red] {e}")


def main():
    parser = argparse.ArgumentParser(description="Hive CLI")
    parser.add_argument(
        "--no_auth",
        action="store_true",
        default=False,
        help="Disable authentication",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        default=False,
        help="Disable SSL certificate verification",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init command
    parser_init = subparsers.add_parser("init", help="Initialize the Hive configuration")
    parser_init.set_defaults(func=init)

    # login command
    parser_login = subparsers.add_parser("login", help="Log in to the Hive platform")
    parser_login.set_defaults(func=login)

    # logout command
    parser_logout = subparsers.add_parser("logout", help="Log out and clear stored credentials")
    parser_logout.set_defaults(func=logout)

    # edit command
    parser_edit = subparsers.add_parser("edit", help="Edit Hive configuration")
    edit_subparsers = parser_edit.add_subparsers(dest="edit_target")
    parser_edit_config = edit_subparsers.add_parser(
        "config", help="Edit the Hive configuration file"
    )
    parser_edit_config.add_argument(
        "-f",
        "--config",
        default=os.path.expandvars("$HOME/.hive/config.yaml"),
        help="Path to the config file, defaults to ~/.hive/config.yaml",
    ).completer = config_file_completer
    parser_edit_config.set_defaults(func=edit_cli)

    # create command
    parser_create = subparsers.add_parser("create", help="Create resources")
    create_subparsers = parser_create.add_subparsers(dest="create_target")

    parser_create_exp = create_subparsers.add_parser(
        "experiment", aliases=["exp"], help="Create a new experiment"
    )
    parser_create_exp.add_argument(
        "name",
        help="Name of the experiment, if it ends with '-', a random suffix will be added for uniqueness",
    )
    parser_create_exp.add_argument(
        "-f",
        "--config",
        default=os.path.expandvars("$HOME/.hive/config.yaml"),
        help="Path to the config file, default to ~/.hive/config.yaml",
    ).completer = config_file_completer
    parser_create_exp.set_defaults(func=create_experiment)

    # delete command
    parser_delete = subparsers.add_parser("delete", help="Delete resources")
    delete_subparsers = parser_delete.add_subparsers(dest="delete_target")
    parser_delete_exp = delete_subparsers.add_parser(
        "experiment", aliases=["exp", "exp"], help="Delete one or more experiments"
    )
    parser_delete_exp.add_argument(
        "name", nargs="+", help="Name(s) of the experiment(s) to delete"
    ).completer = experiment_completer
    parser_delete_exp.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    parser_delete_exp.add_argument(
        "-f",
        "--config",
        default=os.path.expandvars("$HOME/.hive/config.yaml"),
        help="Path to the config file, default to ~/.hive/config.yaml",
    ).completer = config_file_completer
    parser_delete_exp.set_defaults(func=delete_experiments)

    # list command
    parser_list = subparsers.add_parser("list", help="List resources")
    list_subparsers = parser_list.add_subparsers(dest="list_target")

    # list experiments
    parser_list_exp = list_subparsers.add_parser(
        "experiments", aliases=["exp", "exps"], help="List all experiments"
    )
    parser_list_exp.set_defaults(func=list_experiments)

    # get command
    parser_get = subparsers.add_parser("get", help="Get resource details")
    get_subparsers = parser_get.add_subparsers(dest="get_target")

    # get experiment
    parser_get_exp = get_subparsers.add_parser(
        "experiment", aliases=["exp"], help="Get experiment details"
    )
    parser_get_exp.add_argument(
        "name", help="Name of the experiment"
    ).completer = experiment_completer
    parser_get_exp.set_defaults(func=get_experiment)

    argcomplete.autocomplete(parser)
    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
