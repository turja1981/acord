"""
Upgrade State Management

Defines the state schema for the LangGraph workflow, tracking all aspects
of the Java/Spring Boot upgrade process.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Optional

from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages


class UpgradePhase(str, Enum):
    """Phases of the upgrade workflow."""

    INITIALIZATION = "initialization"
    ANALYSIS = "analysis"
    DEPENDENCY_UPGRADE = "dependency_upgrade"
    CODE_MIGRATION = "code_migration"
    BUILD = "build"
    ERROR_RESOLUTION = "error_resolution"
    TESTING = "testing"
    DEPLOYMENT_PREP = "deployment_prep"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentMessage(BaseModel):
    """Message from an agent."""

    agent_name: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DependencyInfo(BaseModel):
    """Information about a project dependency."""

    group_id: str
    artifact_id: str
    current_version: str
    target_version: Optional[str] = None
    scope: str = "compile"
    is_spring: bool = False
    requires_migration: bool = False
    breaking_changes: list[str] = Field(default_factory=list)
    migration_notes: str = ""


class CodeChange(BaseModel):
    """Represents a code change made during upgrade."""

    file_path: str
    change_type: str  # "modify", "create", "delete", "rename"
    description: str
    old_content: Optional[str] = None
    new_content: Optional[str] = None
    line_numbers: Optional[tuple[int, int]] = None
    agent: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ErrorInfo(BaseModel):
    """Information about a build or runtime error."""

    error_type: str  # "compilation", "test", "runtime", "dependency"
    message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    column: Optional[int] = None
    stack_trace: Optional[str] = None
    suggested_fix: Optional[str] = None
    resolution_attempts: int = 0
    resolved: bool = False


class BuildResult(BaseModel):
    """Result of a Maven build attempt."""

    success: bool
    phase: str  # "compile", "test", "package", "install"
    duration_seconds: float = 0.0
    output: str = ""
    errors: list[ErrorInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TestResult(BaseModel):
    """Result of test execution."""

    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    failed_tests: list[str] = Field(default_factory=list)
    error_tests: list[str] = Field(default_factory=list)


class ModuleState(BaseModel):
    """State for a single module in a multi-module project."""

    name: str
    path: str
    pom_path: str
    artifact_id: str
    is_parent: bool = False
    parent_name: Optional[str] = None

    # Module-specific state
    java_version: Optional[str] = None
    spring_boot_version: Optional[str] = None
    dependencies: list[DependencyInfo] = Field(default_factory=list)

    # Module build state
    build_successful: bool = False
    tests_passed: bool = False
    errors: list[ErrorInfo] = Field(default_factory=list)

    # Changes made to this module
    code_changes: list[CodeChange] = Field(default_factory=list)
    pom_changes: list[CodeChange] = Field(default_factory=list)


class ProjectInfo(BaseModel):
    """Information about the Java project."""

    project_path: str
    group_id: Optional[str] = None
    artifact_id: Optional[str] = None
    current_java_version: Optional[str] = None
    current_spring_boot_version: Optional[str] = None
    packaging: str = "jar"
    modules: list[str] = Field(default_factory=list)
    is_multi_module: bool = False
    parent_pom: Optional[str] = None

    # Multi-module specific
    module_states: dict[str, ModuleState] = Field(default_factory=dict)
    build_order: list[str] = Field(default_factory=list)
    shared_properties: dict[str, str] = Field(default_factory=dict)


class UpgradeConfig(BaseModel):
    """Configuration for the upgrade process."""

    target_java_version: str = "21"
    target_spring_boot_version: str = "3.2.0"
    upgrade_dependencies: bool = True
    run_tests: bool = True
    create_backup: bool = True
    auto_fix_errors: bool = True
    max_error_fix_attempts: int = 3


class UpgradeState(BaseModel):
    """
    Main state for the Java Upgrade LangGraph workflow.

    This state is passed between agents and contains all information
    needed to track and execute the upgrade process.
    """

    # Workflow control
    phase: UpgradePhase = UpgradePhase.INITIALIZATION
    iteration: int = 0
    max_iterations: int = 10
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    # Messages with LangGraph reducer
    messages: Annotated[list, add_messages] = Field(default_factory=list)

    # Project information
    project_info: Optional[ProjectInfo] = None
    upgrade_config: UpgradeConfig = Field(default_factory=UpgradeConfig)

    # Analysis results
    source_files: list[str] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)
    dependencies: list[DependencyInfo] = Field(default_factory=list)
    deprecated_apis: list[dict[str, Any]] = Field(default_factory=list)
    migration_patterns: list[dict[str, Any]] = Field(default_factory=list)

    # Changes made
    code_changes: list[CodeChange] = Field(default_factory=list)
    pom_changes: list[CodeChange] = Field(default_factory=list)
    config_changes: list[CodeChange] = Field(default_factory=list)

    # Build and test results
    build_results: list[BuildResult] = Field(default_factory=list)
    test_results: Optional[TestResult] = None
    current_errors: list[ErrorInfo] = Field(default_factory=list)
    resolved_errors: list[ErrorInfo] = Field(default_factory=list)

    # Agent tracking
    agent_history: list[AgentMessage] = Field(default_factory=list)
    current_agent: Optional[str] = None
    pending_actions: list[dict[str, Any]] = Field(default_factory=list)

    # Metrics
    total_files_modified: int = 0
    total_dependencies_upgraded: int = 0
    total_errors_resolved: int = 0
    total_build_attempts: int = 0

    # Status flags
    analysis_complete: bool = False
    dependencies_upgraded: bool = False
    code_migrated: bool = False
    build_successful: bool = False
    tests_passed: bool = False
    ready_for_deployment: bool = False

    # Error state
    fatal_error: Optional[str] = None
    requires_manual_intervention: bool = False
    manual_intervention_reason: Optional[str] = None

    model_config = {"arbitrary_types_allowed": True}

    def add_agent_message(self, agent_name: str, content: str, **metadata: Any) -> None:
        """Add a message from an agent."""
        self.agent_history.append(
            AgentMessage(agent_name=agent_name, content=content, metadata=metadata)
        )

    def add_code_change(self, change: CodeChange) -> None:
        """Record a code change."""
        self.code_changes.append(change)
        self.total_files_modified += 1

    def add_error(self, error: ErrorInfo) -> None:
        """Add an error to track."""
        self.current_errors.append(error)

    def resolve_error(self, error: ErrorInfo) -> None:
        """Mark an error as resolved."""
        error.resolved = True
        self.resolved_errors.append(error)
        if error in self.current_errors:
            self.current_errors.remove(error)
        self.total_errors_resolved += 1

    def add_build_result(self, result: BuildResult) -> None:
        """Add a build result."""
        self.build_results.append(result)
        self.total_build_attempts += 1
        self.build_successful = result.success

    def get_latest_build(self) -> Optional[BuildResult]:
        """Get the most recent build result."""
        return self.build_results[-1] if self.build_results else None

    def get_unresolved_errors(self) -> list[ErrorInfo]:
        """Get all unresolved errors."""
        return [e for e in self.current_errors if not e.resolved]

    def should_continue(self) -> bool:
        """Check if the workflow should continue."""
        if self.fatal_error:
            return False
        if self.requires_manual_intervention:
            return False
        if self.iteration >= self.max_iterations:
            return False
        if self.phase == UpgradePhase.COMPLETED:
            return False
        if self.phase == UpgradePhase.FAILED:
            return False
        return True

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the upgrade state."""
        return {
            "phase": self.phase.value,
            "iteration": self.iteration,
            "build_successful": self.build_successful,
            "tests_passed": self.tests_passed,
            "files_modified": self.total_files_modified,
            "dependencies_upgraded": self.total_dependencies_upgraded,
            "errors_resolved": self.total_errors_resolved,
            "pending_errors": len(self.get_unresolved_errors()),
            "ready_for_deployment": self.ready_for_deployment,
        }
