"""
Application settings and configuration management.

Provides centralized configuration for the Java upgrade workflow.
"""

import os
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class MavenSettings(BaseModel):
    """Maven build configuration."""

    maven_home: Optional[str] = Field(default=None, description="MAVEN_HOME path")
    maven_opts: str = Field(default="-Xmx2g", description="Maven JVM options")
    settings_file: Optional[str] = Field(default=None, description="Custom settings.xml path")
    local_repo: Optional[str] = Field(default=None, description="Local repository path")
    profiles: list[str] = Field(default_factory=list, description="Active Maven profiles")
    skip_tests: bool = Field(default=False, description="Skip tests during build")
    offline: bool = Field(default=False, description="Run in offline mode")


class JavaSettings(BaseModel):
    """Java configuration."""

    java_home: Optional[str] = Field(default=None, description="JAVA_HOME path")
    source_version: str = Field(default="11", description="Current Java source version")
    target_version: str = Field(default="21", description="Target Java version for upgrade")
    supported_versions: list[str] = Field(
        default=["8", "11", "17", "21"],
        description="Supported Java versions"
    )


class SpringBootSettings(BaseModel):
    """Spring Boot configuration."""

    current_version: Optional[str] = Field(default=None, description="Current Spring Boot version")
    target_version: str = Field(default="3.2.0", description="Target Spring Boot version")
    migration_guide_url: str = Field(
        default="https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-3.0-Migration-Guide",
        description="Migration guide URL"
    )


class WorkflowSettings(BaseModel):
    """Workflow execution settings."""

    max_iterations: int = Field(default=10, description="Maximum workflow iterations")
    max_build_retries: int = Field(default=5, description="Maximum build retry attempts")
    error_resolution_attempts: int = Field(default=3, description="Attempts per error type")
    parallel_agents: bool = Field(default=False, description="Enable parallel agent execution")
    checkpoint_enabled: bool = Field(default=True, description="Enable workflow checkpoints")
    checkpoint_dir: str = Field(default=".workflow_checkpoints", description="Checkpoint directory")


class GitSettings(BaseModel):
    """Git configuration."""

    auto_commit: bool = Field(default=True, description="Auto-commit changes")
    commit_prefix: str = Field(default="[java-upgrade]", description="Commit message prefix")
    branch_prefix: str = Field(default="upgrade/java-", description="Branch name prefix")
    create_branch: bool = Field(default=True, description="Create new branch for upgrade")


from pydantic import BaseModel


class Settings(BaseSettings):
    """
    Main application settings.

    Configuration sources (in order of precedence):
    1. Environment variables
    2. .env file
    3. Default values
    """

    # Project settings
    project_path: str = Field(default=".", description="Path to Java project")
    output_dir: str = Field(default="./upgrade_output", description="Output directory")
    verbose: bool = Field(default=False, description="Enable verbose logging")
    dry_run: bool = Field(default=False, description="Dry run mode (no actual changes)")

    # Component settings
    maven: MavenSettings = Field(default_factory=MavenSettings)
    java: JavaSettings = Field(default_factory=JavaSettings)
    spring_boot: SpringBootSettings = Field(default_factory=SpringBootSettings)
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)
    git: GitSettings = Field(default_factory=GitSettings)

    # LiteLLM config path
    litellm_config_path: Optional[str] = Field(
        default=None,
        description="Path to LiteLLM configuration YAML"
    )

    model_config = {
        "env_prefix": "JAVA_UPGRADE_",
        "env_file": ".env",
        "env_nested_delimiter": "__",
        "extra": "allow"
    }

    @property
    def project_root(self) -> Path:
        """Get the project root path."""
        return Path(self.project_path).resolve()

    @property
    def pom_file(self) -> Path:
        """Get the path to pom.xml."""
        return self.project_root / "pom.xml"

    @property
    def src_main_java(self) -> Path:
        """Get the main Java source directory."""
        return self.project_root / "src" / "main" / "java"

    @property
    def src_test_java(self) -> Path:
        """Get the test Java source directory."""
        return self.project_root / "src" / "test" / "java"

    def get_maven_command(self) -> list[str]:
        """Get the Maven command with configured options."""
        cmd = ["mvn"]

        if self.maven.settings_file:
            cmd.extend(["-s", self.maven.settings_file])

        if self.maven.local_repo:
            cmd.extend([f"-Dmaven.repo.local={self.maven.local_repo}"])

        if self.maven.profiles:
            cmd.extend(["-P", ",".join(self.maven.profiles)])

        if self.maven.offline:
            cmd.append("-o")

        return cmd

    def ensure_directories(self) -> None:
        """Ensure required directories exist."""
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        if self.workflow.checkpoint_enabled:
            Path(self.workflow.checkpoint_dir).mkdir(parents=True, exist_ok=True)
