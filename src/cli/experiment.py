from typing import Any, Dict

from cli.config import HiveConfig
from cli.utils import time as utiltime


def build_experiment_crd(config: HiveConfig, experiment_name: str) -> Dict[str, Any]:
    """
    Build a Kubernetes Experiment CRD from HiveConfig.

    Args:
        config: The Hive configuration
        experiment_name: Name of the experiment

    Returns:
        Dictionary representing the Experiment CRD
    """
    # Build the basic experiment structure
    experiment = {
        "apiVersion": "core.hiverge.io/v1alpha1",
        "kind": "Experiment",
        "metadata": {
            "name": experiment_name,
        },
        "spec": {
            "runtime": {
                "numAgents": config.runtime.num_agents,
                "maxRuntimeSeconds": config.runtime.max_runtime_seconds,
                "maxIterations": config.runtime.max_iterations,
            },
            "repo": {
                "source": config.repo.source,
                "branch": config.repo.branch,
                "evaluationScript": config.repo.evaluation_script,
                "evolveFilesAndRanges": config.repo.evolve_files_and_ranges,
            },
            "sandbox": {
                "baseImage": config.sandbox.base_image,
                "workdir": config.sandbox.workdir,
                "timeout": config.sandbox.timeout,
                "resources": {
                    "limits": {
                        "cpu": config.sandbox.resources.cpu,
                        "memory": config.sandbox.resources.memory,
                    },
                },
            },
        },
    }

    # Add optional repo fields
    if config.repo.include_files_and_ranges:
        experiment["spec"]["repo"]["includeFilesAndRanges"] = config.repo.include_files_and_ranges

    # Add optional sandbox fields
    if config.sandbox.base_image:
        experiment["spec"]["sandbox"]["baseImage"] = config.sandbox.base_image

    if config.sandbox.resources.accelerators:
        experiment["spec"]["sandbox"]["resources"]["accelerators"] = (
            config.sandbox.resources.accelerators
        )

    if config.sandbox.resources.shmsize:
        experiment["spec"]["sandbox"]["resources"]["shmsize"] = config.sandbox.resources.shmsize

    if config.sandbox.resources.extended_resources:
        experiment["spec"]["sandbox"]["resources"]["limits"].update(
            config.sandbox.resources.extended_resources
        )

    if config.sandbox.envs:
        experiment["spec"]["sandbox"]["envs"] = [
            {"name": env.name, "value": env.value} for env in config.sandbox.envs
        ]

    if config.sandbox.setup_script:
        experiment["spec"]["sandbox"]["setupScript"] = config.sandbox.setup_script

    if config.sandbox.services:
        experiment["spec"]["sandbox"]["services"] = [
            {
                "name": svc.name,
                "image": svc.image,
                **(
                    {"ports": [{"port": p.port, "protocol": p.protocol} for p in svc.ports]}
                    if svc.ports
                    else {}
                ),
                **(
                    {"envs": [{"name": e.name, "value": e.value} for e in svc.envs]}
                    if svc.envs
                    else {}
                ),
                **({"command": svc.command} if svc.command else {}),
                **({"args": svc.args} if svc.args else {}),
                "resources": {
                    "cpu": svc.resources.cpu,
                    "memory": svc.resources.memory,
                },
            }
            for svc in config.sandbox.services
        ]

    # Add optional prompt configuration
    if config.prompt:
        experiment["spec"]["prompt"] = {}
        if config.prompt.context:
            experiment["spec"]["prompt"]["context"] = config.prompt.context
        if config.prompt.ideas:
            experiment["spec"]["prompt"]["ideas"] = config.prompt.ideas
        if config.prompt.enable_evolution:
            experiment["spec"]["prompt"]["enableEvolution"] = config.prompt.enable_evolution

    # Add coordinator config
    if config.coordinator_config_name:
        experiment["spec"]["coordinatorConfigName"] = config.coordinator_config_name

    # TODO: quick hack to support private github repo, will be replaced by github app in the future.
    if config.repo.github_token:
        experiment["metadata"]["annotations"] = {
            "github.com/token": config.repo.github_token,
        }

    return experiment


def generate_experiment_name(base_name: str) -> str:
    """
    Generate a unique experiment name based on the base name and current timestamp.
    If the base name ends with '-', it will be suffixed with a timestamp.

    Raises:
        ValueError: If the name contains uppercase characters or exceeds 63 characters
    """

    if any(c.isupper() for c in base_name):
        raise ValueError("Experiment name must be lowercase.")

    experiment_name = base_name

    # A generated experiment name will be returned directly.
    if experiment_name.endswith("-"):
        hash = utiltime.now_2_hash()
        experiment_name = f"{base_name}{hash}"

    # Kubernetes DNS label limit (RFC 1123)
    if len(experiment_name) > 63:
        raise ValueError(
            f"Experiment name must be no more than 63 characters, got {len(experiment_name)}: '{experiment_name}'"
        )

    return experiment_name
