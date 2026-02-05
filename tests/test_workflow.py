"""
Tests for the Java Upgrade Workflow.
"""

import pytest
from unittest.mock import Mock, patch

from java_upgrade_workflow.config.litellm_config import (
    LiteLLMConfig,
    ModelConfig,
    AgentModelMapping,
    create_default_config,
)
from java_upgrade_workflow.state.upgrade_state import (
    UpgradeState,
    UpgradePhase,
    ProjectInfo,
    UpgradeConfig,
    DependencyInfo,
    ErrorInfo,
    BuildResult,
)


class TestLiteLLMConfig:
    """Tests for LiteLLM configuration."""

    def test_create_default_config(self):
        """Test creating default configuration."""
        config = create_default_config()

        assert config.default_model == "gpt-4-turbo"
        assert config.enable_caching is True
        assert config.enable_cost_tracking is True
        assert "gpt-4-turbo" in config.models
        assert "claude-3-opus" in config.models

    def test_model_config(self):
        """Test model configuration."""
        model = ModelConfig(
            model_name="gpt-4",
            provider="openai",
            api_key_env="OPENAI_API_KEY",
            max_tokens=4096,
            temperature=0.1,
        )

        assert model.model_name == "gpt-4"
        assert model.provider == "openai"
        assert model.max_tokens == 4096

    def test_agent_model_mapping(self):
        """Test agent model mapping."""
        mapping = AgentModelMapping()

        assert mapping.code_analyzer == "gpt-4-turbo"
        assert mapping.code_migrator == "claude-3-opus"

    def test_get_model_for_agent(self):
        """Test getting model for specific agent."""
        config = create_default_config()

        assert config.get_model_for_agent("code_analyzer") == "gpt-4-turbo"
        assert config.get_model_for_agent("code_migrator") == "claude-3-opus"
        assert config.get_model_for_agent("unknown_agent") == config.default_model


class TestUpgradeState:
    """Tests for upgrade state management."""

    def test_initial_state(self):
        """Test initial state creation."""
        state = UpgradeState()

        assert state.phase == UpgradePhase.INITIALIZATION
        assert state.iteration == 0
        assert state.build_successful is False
        assert state.tests_passed is False
        assert len(state.current_errors) == 0

    def test_state_with_project_info(self):
        """Test state with project info."""
        state = UpgradeState(
            project_info=ProjectInfo(
                project_path="/test/path",
                group_id="com.example",
                artifact_id="test-app",
                current_java_version="11",
            )
        )

        assert state.project_info.project_path == "/test/path"
        assert state.project_info.current_java_version == "11"

    def test_add_error(self):
        """Test adding errors to state."""
        state = UpgradeState()
        error = ErrorInfo(
            error_type="compilation",
            message="cannot find symbol",
            file_path="/test/File.java",
            line_number=42,
        )

        state.add_error(error)

        assert len(state.current_errors) == 1
        assert state.current_errors[0].message == "cannot find symbol"

    def test_resolve_error(self):
        """Test resolving errors."""
        state = UpgradeState()
        error = ErrorInfo(
            error_type="compilation",
            message="test error",
        )

        state.add_error(error)
        state.resolve_error(error)

        assert len(state.current_errors) == 0
        assert len(state.resolved_errors) == 1
        assert state.total_errors_resolved == 1

    def test_add_build_result(self):
        """Test adding build results."""
        state = UpgradeState()
        result = BuildResult(
            success=True,
            phase="compile",
            duration_seconds=10.5,
        )

        state.add_build_result(result)

        assert len(state.build_results) == 1
        assert state.build_successful is True
        assert state.total_build_attempts == 1

    def test_should_continue(self):
        """Test workflow continuation logic."""
        state = UpgradeState()

        # Should continue initially
        assert state.should_continue() is True

        # Should not continue after completion
        state.phase = UpgradePhase.COMPLETED
        assert state.should_continue() is False

        # Should not continue after failure
        state.phase = UpgradePhase.BUILD
        state.fatal_error = "Critical error"
        assert state.should_continue() is False

        # Should not continue after max iterations
        state.fatal_error = None
        state.iteration = 10
        state.max_iterations = 10
        assert state.should_continue() is False

    def test_get_summary(self):
        """Test getting state summary."""
        state = UpgradeState(
            phase=UpgradePhase.BUILD,
            build_successful=True,
            tests_passed=True,
            total_files_modified=5,
            total_dependencies_upgraded=3,
        )

        summary = state.get_summary()

        assert summary["phase"] == "build"
        assert summary["build_successful"] is True
        assert summary["files_modified"] == 5


class TestDependencyInfo:
    """Tests for dependency information."""

    def test_dependency_creation(self):
        """Test creating dependency info."""
        dep = DependencyInfo(
            group_id="org.springframework.boot",
            artifact_id="spring-boot-starter-web",
            current_version="2.7.0",
            target_version="3.2.0",
            is_spring=True,
        )

        assert dep.group_id == "org.springframework.boot"
        assert dep.is_spring is True
        assert dep.requires_migration is False


class TestUpgradeConfig:
    """Tests for upgrade configuration."""

    def test_default_config(self):
        """Test default upgrade config."""
        config = UpgradeConfig()

        assert config.target_java_version == "21"
        assert config.target_spring_boot_version == "3.2.0"
        assert config.upgrade_dependencies is True
        assert config.run_tests is True

    def test_custom_config(self):
        """Test custom upgrade config."""
        config = UpgradeConfig(
            target_java_version="17",
            target_spring_boot_version="3.1.0",
            run_tests=False,
        )

        assert config.target_java_version == "17"
        assert config.target_spring_boot_version == "3.1.0"
        assert config.run_tests is False


class TestWorkflowIntegration:
    """Integration tests for the workflow."""

    @pytest.mark.skip(reason="Requires LLM API keys")
    def test_workflow_creation(self):
        """Test workflow creation."""
        from java_upgrade_workflow.workflow import JavaUpgradeWorkflow

        workflow = JavaUpgradeWorkflow()

        assert workflow.agents is not None
        assert "code_analyzer" in workflow.agents
        assert "build_agent" in workflow.agents

    @pytest.mark.skip(reason="Requires LLM API keys and Maven project")
    def test_workflow_run(self):
        """Test running the workflow."""
        from java_upgrade_workflow.workflow import JavaUpgradeWorkflow

        workflow = JavaUpgradeWorkflow()
        result = workflow.run(
            project_path="./test-project",
            target_java_version="21",
            dry_run=True,
        )

        assert result is not None
        assert result.phase is not None
