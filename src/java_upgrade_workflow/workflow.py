"""
Java Upgrade LangGraph Workflow

Main workflow orchestration using LangGraph for the Java/Spring Boot upgrade process.
Supports both single-module and multi-module Maven projects with parent-child dependencies.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from java_upgrade_workflow.agents.base_agent import BaseUpgradeAgent
from java_upgrade_workflow.agents.code_analyzer import CodeAnalyzerAgent
from java_upgrade_workflow.agents.dependency_upgrader import DependencyUpgraderAgent
from java_upgrade_workflow.agents.code_migrator import CodeMigratorAgent
from java_upgrade_workflow.agents.build_agent import BuildAgent
from java_upgrade_workflow.agents.error_resolver import ErrorResolverAgent
from java_upgrade_workflow.agents.deployment_agent import DeploymentAgent
from java_upgrade_workflow.config.litellm_config import LiteLLMConfig, create_default_config
from java_upgrade_workflow.config.settings import Settings
from java_upgrade_workflow.state.upgrade_state import (
    ProjectInfo,
    UpgradeConfig,
    UpgradePhase,
    UpgradeState,
    ModuleState,
)
from java_upgrade_workflow.tools.maven_tools import MultiModulePomAnalyzer
from java_upgrade_workflow.utils.logging import get_logger
from java_upgrade_workflow.utils.comparison_report import (
    ComparisonReportGenerator,
    ChangeType,
)
from java_upgrade_workflow.utils.agent_tracking import AgentTracker


logger = get_logger(__name__)


class JavaUpgradeWorkflow:
    """
    LangGraph-based workflow for Java/Spring Boot upgrades.

    This workflow orchestrates multiple specialized agents to:
    1. Analyze the existing codebase
    2. Upgrade dependencies (Java, Spring Boot, etc.)
    3. Migrate source code (javax to jakarta, JUnit 4 to 5, etc.)
    4. Build and test the application
    5. Resolve any errors automatically
    6. Prepare for deployment

    The workflow uses LiteLLM for externalized LLM configuration,
    allowing easy switching between different LLM providers.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        llm_config: Optional[LiteLLMConfig] = None,
    ):
        """
        Initialize the Java Upgrade Workflow.

        Args:
            settings: Application settings
            llm_config: LiteLLM configuration for agent LLM calls
        """
        self.settings = settings or Settings()
        self.llm_config = llm_config or create_default_config()

        # Initialize LiteLLM
        self.llm_config.initialize_litellm()

        # Initialize agents
        self.agents: dict[str, BaseUpgradeAgent] = {
            "code_analyzer": CodeAnalyzerAgent(self.llm_config),
            "dependency_upgrader": DependencyUpgraderAgent(self.llm_config),
            "code_migrator": CodeMigratorAgent(self.llm_config),
            "build_agent": BuildAgent(self.llm_config),
            "error_resolver": ErrorResolverAgent(self.llm_config),
            "deployment_agent": DeploymentAgent(self.llm_config),
        }

        # Build the workflow graph
        self.graph = self._build_graph()

        # Checkpointer for state persistence
        self.checkpointer = MemorySaver()

        # Comparison report generator and agent tracker (initialized per run)
        self.report_generator: Optional[ComparisonReportGenerator] = None
        self.agent_tracker: Optional[AgentTracker] = None

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow graph."""
        # Create the graph with UpgradeState
        workflow = StateGraph(UpgradeState)

        # Add nodes for each agent
        workflow.add_node("analyze", self._run_analyzer)
        workflow.add_node("upgrade_dependencies", self._run_dependency_upgrader)
        workflow.add_node("migrate_code", self._run_code_migrator)
        workflow.add_node("build", self._run_build)
        workflow.add_node("resolve_errors", self._run_error_resolver)
        workflow.add_node("prepare_deployment", self._run_deployment)

        # Set entry point
        workflow.set_entry_point("analyze")

        # Add edges
        workflow.add_edge("analyze", "upgrade_dependencies")
        workflow.add_edge("upgrade_dependencies", "migrate_code")
        workflow.add_edge("migrate_code", "build")

        # Conditional edge after build
        workflow.add_conditional_edges(
            "build",
            self._route_after_build,
            {
                "resolve_errors": "resolve_errors",
                "prepare_deployment": "prepare_deployment",
                "end": END,
            }
        )

        # After error resolution, try building again
        workflow.add_conditional_edges(
            "resolve_errors",
            self._route_after_error_resolution,
            {
                "build": "build",
                "end": END,
            }
        )

        # Deployment leads to end
        workflow.add_edge("prepare_deployment", END)

        return workflow.compile(checkpointer=self.checkpointer)

    def _run_analyzer(self, state: UpgradeState) -> UpgradeState:
        """Run the code analyzer agent."""
        logger.info("Running code analyzer...")
        agent = self.agents["code_analyzer"]
        return agent.run(state)

    def _run_dependency_upgrader(self, state: UpgradeState) -> UpgradeState:
        """Run the dependency upgrader agent."""
        logger.info("Running dependency upgrader...")
        agent = self.agents["dependency_upgrader"]
        return agent.run(state)

    def _run_code_migrator(self, state: UpgradeState) -> UpgradeState:
        """Run the code migrator agent."""
        logger.info("Running code migrator...")
        agent = self.agents["code_migrator"]
        return agent.run(state)

    def _run_build(self, state: UpgradeState) -> UpgradeState:
        """Run the build agent."""
        logger.info("Running build agent...")
        state.iteration += 1
        agent = self.agents["build_agent"]
        return agent.run(state)

    def _run_error_resolver(self, state: UpgradeState) -> UpgradeState:
        """Run the error resolver agent."""
        logger.info("Running error resolver...")
        agent = self.agents["error_resolver"]
        return agent.run(state)

    def _run_deployment(self, state: UpgradeState) -> UpgradeState:
        """Run the deployment agent."""
        logger.info("Running deployment agent...")
        agent = self.agents["deployment_agent"]
        return agent.run(state)

    def _route_after_build(
        self, state: UpgradeState
    ) -> Literal["resolve_errors", "prepare_deployment", "end"]:
        """Determine next step after build."""
        # Check if we've exceeded max iterations
        if state.iteration >= state.max_iterations:
            logger.warning("Max iterations reached")
            state.phase = UpgradePhase.FAILED
            return "end"

        # Check for fatal errors
        if state.fatal_error:
            logger.error(f"Fatal error: {state.fatal_error}")
            state.phase = UpgradePhase.FAILED
            return "end"

        # If build failed, try to resolve errors
        if not state.build_successful and state.current_errors:
            return "resolve_errors"

        # If build succeeded and tests passed, proceed to deployment
        if state.build_successful and state.tests_passed:
            return "prepare_deployment"

        # If tests failed, try error resolution
        if state.build_successful and not state.tests_passed:
            return "resolve_errors"

        return "end"

    def _route_after_error_resolution(
        self, state: UpgradeState
    ) -> Literal["build", "end"]:
        """Determine next step after error resolution."""
        # Check iteration limit
        if state.iteration >= state.max_iterations:
            logger.warning("Max iterations reached during error resolution")
            return "end"

        # If errors were resolved, try building again
        if state.total_errors_resolved > 0:
            return "build"

        # If manual intervention is required, stop
        if state.requires_manual_intervention:
            logger.warning(f"Manual intervention required: {state.manual_intervention_reason}")
            return "end"

        # If no progress made, stop
        return "end"

    def _detect_multi_module_project(self, project_path: str) -> tuple[bool, Optional[Any]]:
        """Detect if the project is a multi-module Maven project."""
        try:
            analyzer = MultiModulePomAnalyzer(project_path)
            project = analyzer.analyze()
            return project.is_multi_module, project
        except Exception:
            return False, None

    def _initialize_module_states(
        self,
        project_info: ProjectInfo,
        multi_module_project: Any,
    ) -> None:
        """Initialize module states for a multi-module project."""
        if not multi_module_project:
            return

        for module in multi_module_project.modules:
            project_info.module_states[module.name] = ModuleState(
                name=module.name,
                path=module.path,
                pom_path=module.pom_path,
                artifact_id=module.artifact_id,
                is_parent=module.is_parent,
                parent_name=module.parent_artifact_id,
                java_version=module.java_version,
                spring_boot_version=module.spring_boot_version,
                dependencies=module.dependencies,
            )

        project_info.build_order = multi_module_project.module_order
        project_info.shared_properties = multi_module_project.shared_properties

    def run(
        self,
        project_path: str,
        target_java_version: str = "21",
        target_spring_boot_version: str = "3.2.0",
        run_tests: bool = True,
        dry_run: bool = False,
        generate_report: bool = True,
        report_output_dir: Optional[str] = None,
    ) -> UpgradeState:
        """
        Execute the upgrade workflow.

        Args:
            project_path: Path to the Java project to upgrade
            target_java_version: Target Java version
            target_spring_boot_version: Target Spring Boot version
            run_tests: Whether to run tests after upgrade
            dry_run: If True, don't make actual changes
            generate_report: Whether to generate a comparison report
            report_output_dir: Directory for report output (default: project_path/upgrade_reports)

        Returns:
            Final upgrade state with results
        """
        logger.info(f"Starting Java upgrade workflow for: {project_path}")
        logger.info(f"Target: Java {target_java_version}, Spring Boot {target_spring_boot_version}")

        # Initialize comparison report generator and agent tracker
        self.report_generator = ComparisonReportGenerator(project_path)
        self.agent_tracker = AgentTracker()

        # Detect multi-module project
        is_multi_module, multi_module_project = self._detect_multi_module_project(project_path)

        if is_multi_module:
            logger.info(f"Detected multi-module project with {len(multi_module_project.modules)} modules")
            logger.info(f"Build order: {multi_module_project.module_order}")

        # Initialize project info
        project_info = ProjectInfo(
            project_path=project_path,
            is_multi_module=is_multi_module,
            modules=multi_module_project.module_order if multi_module_project else [],
        )

        # Initialize module states for multi-module projects
        if is_multi_module and multi_module_project:
            self._initialize_module_states(project_info, multi_module_project)

            # Set report project info
            self.report_generator.set_project_info(
                project_name=multi_module_project.parent_module.artifact_id if multi_module_project.parent_module else "unknown",
                is_multi_module=True,
                source_java=multi_module_project.parent_module.java_version if multi_module_project.parent_module else None,
                target_java=target_java_version,
                source_spring=multi_module_project.parent_module.spring_boot_version if multi_module_project.parent_module else None,
                target_spring=target_spring_boot_version,
            )

        # Initialize state
        initial_state = UpgradeState(
            project_info=project_info,
            upgrade_config=UpgradeConfig(
                target_java_version=target_java_version,
                target_spring_boot_version=target_spring_boot_version,
                run_tests=run_tests,
            ),
            max_iterations=self.settings.workflow.max_iterations,
        )

        # Configure thread for checkpointing
        config = {"configurable": {"thread_id": f"upgrade-{datetime.now().isoformat()}"}}

        # Run the workflow
        final_state = initial_state
        try:
            for event in self.graph.stream(initial_state, config):
                # Log progress
                for node_name, node_state in event.items():
                    if isinstance(node_state, UpgradeState):
                        logger.info(
                            f"[{node_name}] Phase: {node_state.phase.value}, "
                            f"Build: {'OK' if node_state.build_successful else 'FAIL'}, "
                            f"Errors: {len(node_state.current_errors)}"
                        )
                        final_state = node_state

            # Get final state
            graph_state = self.graph.get_state(config)
            if graph_state and graph_state.values:
                final_state = UpgradeState(**graph_state.values)

        except Exception as e:
            logger.error(f"Workflow failed with error: {e}")
            final_state.fatal_error = str(e)
            final_state.phase = UpgradePhase.FAILED

        # Generate comparison report
        if generate_report:
            self._generate_comparison_report(final_state, report_output_dir)

        return final_state

    def _generate_comparison_report(
        self,
        state: UpgradeState,
        output_dir: Optional[str] = None,
    ) -> None:
        """Generate comparison report for the upgrade."""
        if not self.report_generator:
            return

        # Record all changes from the state
        for change in state.code_changes:
            self.report_generator.record_change(
                file_path=change.file_path,
                change_type=ChangeType.MODIFIED if change.change_type == "modify" else ChangeType.CREATED,
                agent_name=change.agent,
                description=change.description,
                new_content=change.new_content,
            )

        for change in state.pom_changes:
            self.report_generator.record_change(
                file_path=change.file_path,
                change_type=ChangeType.MODIFIED,
                agent_name=change.agent,
                description=change.description,
                new_content=change.new_content,
                is_parent_pom="parent" in change.file_path.lower() or change.file_path.endswith("pom.xml"),
            )

        # Determine output directory
        if output_dir is None:
            output_dir = str(Path(state.project_info.project_path) / "upgrade_reports") if state.project_info else "./upgrade_reports"

        # Save reports
        try:
            report_paths = self.report_generator.save_reports(output_dir)
            logger.info(f"Comparison reports generated:")
            for format_type, path in report_paths.items():
                logger.info(f"  - {format_type}: {path}")
        except Exception as e:
            logger.error(f"Failed to generate comparison report: {e}")

    async def run_async(
        self,
        project_path: str,
        target_java_version: str = "21",
        target_spring_boot_version: str = "3.2.0",
        run_tests: bool = True,
    ) -> UpgradeState:
        """
        Execute the upgrade workflow asynchronously.

        Args:
            project_path: Path to the Java project to upgrade
            target_java_version: Target Java version
            target_spring_boot_version: Target Spring Boot version
            run_tests: Whether to run tests after upgrade

        Returns:
            Final upgrade state with results
        """
        logger.info(f"Starting async Java upgrade workflow for: {project_path}")

        initial_state = UpgradeState(
            project_info=ProjectInfo(project_path=project_path),
            upgrade_config=UpgradeConfig(
                target_java_version=target_java_version,
                target_spring_boot_version=target_spring_boot_version,
                run_tests=run_tests,
            ),
            max_iterations=self.settings.workflow.max_iterations,
        )

        config = {"configurable": {"thread_id": f"upgrade-{datetime.now().isoformat()}"}}

        try:
            async for event in self.graph.astream(initial_state, config):
                for node_name, node_state in event.items():
                    if isinstance(node_state, UpgradeState):
                        logger.info(f"[{node_name}] Phase: {node_state.phase.value}")

            final_state = self.graph.get_state(config)
            if final_state and final_state.values:
                return UpgradeState(**final_state.values)

            return initial_state

        except Exception as e:
            logger.error(f"Async workflow failed: {e}")
            initial_state.fatal_error = str(e)
            initial_state.phase = UpgradePhase.FAILED
            return initial_state

    def get_workflow_visualization(self) -> str:
        """Get a Mermaid diagram of the workflow."""
        return """
```mermaid
graph TD
    A[Start] --> B[Code Analyzer]
    B --> C[Dependency Upgrader]
    C --> D[Code Migrator]
    D --> E[Build Agent]
    E -->|Build Failed| F[Error Resolver]
    E -->|Build Success| G[Deployment Agent]
    F -->|Errors Fixed| E
    F -->|Cannot Fix| H[End - Manual Intervention]
    G --> I[End - Success]

    style B fill:#e1f5fe
    style C fill:#f3e5f5
    style D fill:#e8f5e9
    style E fill:#fff3e0
    style F fill:#ffebee
    style G fill:#e0f2f1
```
"""
