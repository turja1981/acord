"""State management for Java Upgrade Workflow."""

from java_upgrade_workflow.state.upgrade_state import (
    UpgradeState,
    BuildResult,
    CodeChange,
    DependencyInfo,
    ErrorInfo,
    AgentMessage,
    UpgradePhase,
)

__all__ = [
    "UpgradeState",
    "BuildResult",
    "CodeChange",
    "DependencyInfo",
    "ErrorInfo",
    "AgentMessage",
    "UpgradePhase",
]
