from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator

from cli.utils import logger


class ResourceConfig(BaseModel):
    cpu: str = Field(
        default="1",
        description="The CPU resource request for the sandbox. Default to '1'.",
    )
    memory: str = Field(
        default="2Gi", description="The memory resource limit for the sandbox. Default to '2Gi'."
    )
    accelerators: Optional[str] = Field(
        default=None,
        description="The accelerator resource limit for the sandbox, e.g., 'a100-80gb:8'.",
    )
    shmsize: Optional[str] = Field(
        default=None, description="The size of /dev/shm for the sandbox container, e.g., '1Gi'."
    )
    extended_resources: Optional[dict] = None


class KeyValueSet(BaseModel):
    name: str
    value: str


class PortConfig(BaseModel):
    port: int = Field(
        description="The port number inside the container.",
    )
    protocol: Optional[str] = Field(
        default="TCP",
        description="The protocol for the port. Default to 'TCP'.",
    )


class ServiceConfig(BaseModel):
    name: str
    image: str
    ports: Optional[list[PortConfig]] = None
    envs: Optional[list[KeyValueSet]] = None
    command: Optional[list[str]] = None
    args: Optional[list[str]] = None
    resources: ResourceConfig = Field(
        default_factory=ResourceConfig,
        description="Resource configuration for the service.",
    )


class SandboxConfig(BaseModel):
    base_image: str = Field(
        description="The base Docker image to use for the sandbox.",
    )
    workdir: str = Field(
        default="/app",
        description="The directory to the codebases. Default to /app.",
    )
    setup_script: Optional[str] = Field(
        default=None,
        description="The setup script to run before the experiment starts. This can be used to install dependencies or do any other setup work. Default to None.",
    )
    envs: Optional[list[KeyValueSet]] = Field(
        default=None,
        description="Environment variables to set in the sandbox container.",
    )
    timeout: int = 60
    resources: ResourceConfig = Field(
        default_factory=ResourceConfig,
        description="Resource configuration for the sandbox.",
    )
    services: Optional[list[ServiceConfig]] = Field(
        default=None,
        description="Additional services to run alongside the sandbox.",
    )


class PromptConfig(BaseModel):
    enable_evolution: bool = Field(
        default=False,
        description="Whether to enable evolution for the experiment. Default to False.",
    )
    context: Optional[str] = Field(
        default=None,
        description="Some useful experiment-specific context to provide to the Hive.",
    )
    ideas: Optional[list[str]] = Field(
        default=None,
        description="A list of ideas which will be randomly sampled to inject into the Hive.",
    )


class RepoConfig(BaseModel):
    github_token: Optional[str] = Field(
        default=None,
        description="GitHub token with access to the repository. This is required if the source is a private GitHub repository.",
    )
    source: str
    branch: str = Field(
        default="main",
        description="The branch to use for the experiment. Default to 'main'.",
    )
    evaluation_script: str = Field(
        default="evaluator.py",
        description="The evaluation script to run for the experiment. Default to 'evaluator.py'.",
    )
    evolve_files_and_ranges: str = Field(
        description="Files to evolve, support line ranges like `file.py`, `file.py:1-10`, `file.py:1-10&21-30`."
    )
    include_files_and_ranges: str = Field(
        default="",
        description="Additional files to include in the prompt and their ranges, e.g. `file.py`, `file.py:1-10`, `file.py:1-10&21-30`.",
    )

    @field_validator("source")
    def source_should_not_be_git(cls, v):
        if v.startswith("git@"):
            raise ValueError("Only HTTPS URLs are allowed; git@ SSH URLs are not supported.")
        return v


class RuntimeConfig(BaseModel):
    num_agents: int = Field(
        default=1,
        description="Number of agents to use in the experiment. Default to 1.",
    )
    max_runtime_seconds: int = Field(
        default=-1,
        description="Maximum runtime for the experiment in seconds. \
            -1 means no limit.",
    )
    max_iterations: int = Field(
        default=-1,
        description="Maximum number of iterations for the experiment. \
            -1 means no limit.",
    )


class HiveConfig(BaseModel):
    organization_id: Optional[str] = Field(
        required=True,
        description="The organization ID to associate the experiment with, will be removed in the future.",
    )
    # team_id: str = Field(
    #     description="The team ID to associate the experiment with. This is required for multi-tenant environments.",
    # )
    coordinator_config_name: str = Field(
        default="default-coordinator-config",
        description="The name of the coordinator config to use for the experiment. Default to 'default-coordinator-config'.",
    )
    runtime: RuntimeConfig = Field(
        default_factory=RuntimeConfig, description="Runtime configuration for the experiment."
    )
    repo: RepoConfig = Field(
        default_factory=RepoConfig,
        description="Repository configuration for the experiment.",
    )
    sandbox: SandboxConfig = Field(
        default_factory=SandboxConfig,
        description="Sandbox configuration for the experiment.",
    )
    prompt: Optional[PromptConfig] = None
    log_level: str = Field(
        default="INFO",
        enumerated=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        description="The logging level to use for the experiment. Default to 'INFO'.",
    )


def load_config(file_path: str) -> HiveConfig:
    """Load configuration from a YAML file."""
    with open(file_path, "r") as file:
        config_data = yaml.safe_load(file)
    config = HiveConfig(**config_data)

    # set the logging level.
    logger.set_log_level(config.log_level)

    return config
