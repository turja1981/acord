"""
CLI for Java Upgrade Workflow

Command-line interface for running the Java/Spring Boot upgrade workflow.
"""

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from java_upgrade_workflow.config.litellm_config import LiteLLMConfig
from java_upgrade_workflow.config.settings import Settings
from java_upgrade_workflow.state.upgrade_state import UpgradePhase
from java_upgrade_workflow.utils.logging import setup_logging
from java_upgrade_workflow.workflow import JavaUpgradeWorkflow


app = typer.Typer(
    name="java-upgrade",
    help="Automated Java/Spring Boot upgrade workflow using LangGraph and LiteLLM",
    add_completion=False,
)

console = Console()


@app.command()
def upgrade(
    project_path: str = typer.Argument(
        ".",
        help="Path to the Java/Maven project to upgrade",
    ),
    target_java: str = typer.Option(
        "21",
        "--java",
        "-j",
        help="Target Java version",
    ),
    target_spring_boot: str = typer.Option(
        "3.2.0",
        "--spring-boot",
        "-s",
        help="Target Spring Boot version",
    ),
    run_tests: bool = typer.Option(
        True,
        "--tests/--no-tests",
        help="Run tests after upgrade",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Analyze only, don't make changes",
    ),
    config_file: Optional[str] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to LiteLLM configuration YAML file",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
    output_json: bool = typer.Option(
        False,
        "--json",
        help="Output results as JSON",
    ),
) -> None:
    """
    Upgrade a Java/Spring Boot project to newer versions.

    This command analyzes your project, upgrades dependencies, migrates code,
    builds, and automatically resolves errors.

    Example:
        java-upgrade ./my-project --java 21 --spring-boot 3.2.0
    """
    setup_logging(level="DEBUG" if verbose else "INFO")

    # Validate project path
    project_path = Path(project_path).resolve()
    pom_file = project_path / "pom.xml"

    if not pom_file.exists():
        console.print(
            f"[red]Error:[/red] No pom.xml found in {project_path}",
            style="bold red",
        )
        raise typer.Exit(1)

    # Display configuration
    if not output_json:
        console.print(
            Panel(
                f"[bold]Java Upgrade Workflow[/bold]\n\n"
                f"Project: {project_path}\n"
                f"Target Java: {target_java}\n"
                f"Target Spring Boot: {target_spring_boot}\n"
                f"Run Tests: {run_tests}\n"
                f"Dry Run: {dry_run}",
                title="Configuration",
                border_style="blue",
            )
        )

    # Load configurations
    settings = Settings(project_path=str(project_path), dry_run=dry_run)

    if config_file:
        llm_config = LiteLLMConfig.from_yaml(config_file)
    else:
        from java_upgrade_workflow.config.litellm_config import create_default_config
        llm_config = create_default_config()

    # Create and run workflow
    workflow = JavaUpgradeWorkflow(settings=settings, llm_config=llm_config)

    if not output_json:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Running upgrade workflow...", total=None)

            result = workflow.run(
                project_path=str(project_path),
                target_java_version=target_java,
                target_spring_boot_version=target_spring_boot,
                run_tests=run_tests,
                dry_run=dry_run,
            )

            progress.update(task, completed=True)
    else:
        result = workflow.run(
            project_path=str(project_path),
            target_java_version=target_java,
            target_spring_boot_version=target_spring_boot,
            run_tests=run_tests,
            dry_run=dry_run,
        )

    # Output results
    if output_json:
        print(json.dumps(result.get_summary(), indent=2))
    else:
        _display_results(result)

    # Exit with appropriate code
    if result.phase == UpgradePhase.COMPLETED:
        raise typer.Exit(0)
    elif result.phase == UpgradePhase.FAILED:
        raise typer.Exit(1)
    else:
        raise typer.Exit(2)


@app.command()
def analyze(
    project_path: str = typer.Argument(
        ".",
        help="Path to the Java/Maven project to analyze",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
) -> None:
    """
    Analyze a Java project without making any changes.

    This command scans your project and reports:
    - Current Java and Spring Boot versions
    - Dependencies that need upgrading
    - Deprecated patterns that need migration
    - Estimated upgrade complexity
    """
    setup_logging(level="DEBUG" if verbose else "INFO")

    project_path = Path(project_path).resolve()
    pom_file = project_path / "pom.xml"

    if not pom_file.exists():
        console.print(f"[red]Error:[/red] No pom.xml found in {project_path}")
        raise typer.Exit(1)

    console.print(f"[bold]Analyzing project:[/bold] {project_path}\n")

    # Run analysis only
    from java_upgrade_workflow.config.litellm_config import create_default_config
    from java_upgrade_workflow.agents.code_analyzer import CodeAnalyzerAgent
    from java_upgrade_workflow.state.upgrade_state import ProjectInfo, UpgradeState

    llm_config = create_default_config()
    analyzer = CodeAnalyzerAgent(llm_config)

    state = UpgradeState(
        project_info=ProjectInfo(project_path=str(project_path))
    )

    result = analyzer.run(state)

    # Display analysis results
    _display_analysis(result)


@app.command()
def init_config(
    output_path: str = typer.Option(
        "./litellm_config.yaml",
        "--output",
        "-o",
        help="Output path for configuration file",
    ),
) -> None:
    """
    Generate a sample LiteLLM configuration file.

    This creates a YAML configuration file that you can customize
    for your LLM provider (OpenAI, Anthropic, Azure, etc.).
    """
    sample_config = """# LiteLLM Configuration for Java Upgrade Workflow
# See https://docs.litellm.ai for all options

# Default model for all agents (if not specified per-agent)
default_model: gpt-4-turbo

# Enable response caching
enable_caching: true
cache_type: local

# Enable cost tracking
enable_cost_tracking: true

# Model configurations
models:
  gpt-4-turbo:
    model_name: gpt-4-turbo-preview
    provider: openai
    api_key_env: OPENAI_API_KEY
    max_tokens: 4096
    temperature: 0.1
    timeout: 120
    max_retries: 3
    input_cost_per_1k: 0.01
    output_cost_per_1k: 0.03
    fallback_models:
      - gpt-4
      - gpt-3.5-turbo

  claude-3-opus:
    model_name: claude-3-opus-20240229
    provider: anthropic
    api_key_env: ANTHROPIC_API_KEY
    max_tokens: 4096
    temperature: 0.1
    timeout: 120
    max_retries: 3
    input_cost_per_1k: 0.015
    output_cost_per_1k: 0.075

  azure-gpt-4:
    model_name: azure/gpt-4
    provider: azure
    api_key_env: AZURE_API_KEY
    api_base: ${AZURE_API_BASE}
    max_tokens: 8192
    temperature: 0.1

# Agent-specific model assignments
agent_models:
  code_analyzer: gpt-4-turbo
  dependency_upgrader: gpt-4-turbo
  code_migrator: claude-3-opus  # Claude excels at code transformation
  build_agent: gpt-4-turbo
  error_resolver: claude-3-opus
  deployment_agent: gpt-4-turbo

# Fallback configuration
enable_fallbacks: true
fallback_strategy: sequential
"""

    output_path = Path(output_path)
    output_path.write_text(sample_config)

    console.print(f"[green]Configuration file created:[/green] {output_path}")
    console.print("\n[yellow]Remember to set your API keys:[/yellow]")
    console.print("  export OPENAI_API_KEY=your-key")
    console.print("  export ANTHROPIC_API_KEY=your-key")


def _display_results(state) -> None:
    """Display upgrade results in a formatted table."""
    # Summary table
    table = Table(title="Upgrade Results", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    summary = state.get_summary()
    table.add_row("Status", state.phase.value.upper())
    table.add_row("Build Successful", "Yes" if summary["build_successful"] else "No")
    table.add_row("Tests Passed", "Yes" if summary["tests_passed"] else "No")
    table.add_row("Files Modified", str(summary["files_modified"]))
    table.add_row("Dependencies Upgraded", str(summary["dependencies_upgraded"]))
    table.add_row("Errors Resolved", str(summary["errors_resolved"]))
    table.add_row("Pending Errors", str(summary["pending_errors"]))
    table.add_row("Ready for Deployment", "Yes" if summary["ready_for_deployment"] else "No")

    console.print(table)

    # Show errors if any
    if state.current_errors:
        console.print("\n[bold red]Unresolved Errors:[/bold red]")
        for error in state.current_errors[:5]:
            console.print(f"  - [{error.error_type}] {error.message[:100]}")
        if len(state.current_errors) > 5:
            console.print(f"  ... and {len(state.current_errors) - 5} more")

    # Show report location
    if state.phase == UpgradePhase.COMPLETED:
        console.print(
            "\n[green]Upgrade complete![/green] See UPGRADE_REPORT.md for details."
        )


def _display_analysis(state) -> None:
    """Display analysis results."""
    if state.project_info:
        console.print(Panel(
            f"Java Version: {state.project_info.current_java_version or 'Unknown'}\n"
            f"Spring Boot: {state.project_info.current_spring_boot_version or 'Not detected'}\n"
            f"Source Files: {len(state.source_files)}\n"
            f"Test Files: {len(state.test_files)}\n"
            f"Dependencies: {len(state.dependencies)}",
            title="Project Info",
            border_style="blue",
        ))

    if state.deprecated_apis:
        console.print("\n[bold]Deprecated Patterns Found:[/bold]")
        for pattern in state.deprecated_apis:
            console.print(
                f"  - [{pattern.get('severity', 'medium').upper()}] "
                f"{pattern.get('name')}: {pattern.get('occurrences', 0)} occurrences"
            )
            console.print(f"    {pattern.get('description', '')}")

    if state.migration_patterns:
        console.print("\n[bold]Migration Required:[/bold]")
        for migration in state.migration_patterns:
            console.print(
                f"  - {migration.get('type')}: "
                f"{migration.get('from')} -> {migration.get('to')}"
            )


if __name__ == "__main__":
    app()
