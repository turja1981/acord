"""
Deployment Agent

Handles deployment preparation and validation.
"""

from pathlib import Path
from typing import Any

from java_upgrade_workflow.agents.base_agent import AgentConfig, BaseUpgradeAgent
from java_upgrade_workflow.config.litellm_config import LiteLLMConfig
from java_upgrade_workflow.state.upgrade_state import (
    CodeChange,
    UpgradePhase,
    UpgradeState,
)
from java_upgrade_workflow.tools.git_tools import (
    commit_changes,
    create_branch,
    get_git_status,
)
from java_upgrade_workflow.tools.maven_tools import run_maven_build


DEPLOYMENT_AGENT_PROMPT = """You are a Java Deployment Preparation Expert.

Your role is to prepare upgraded applications for production deployment:

1. Build Validation:
   - Verify final build is successful
   - Check artifact generation
   - Validate all tests pass

2. Deployment Checklist:
   - Database migration scripts ready
   - Configuration changes documented
   - Rollback plan in place
   - Monitoring/alerting updated

3. Documentation:
   - Update README with new requirements
   - Document breaking changes
   - Update deployment procedures

4. Git Operations:
   - Commit all changes with clear messages
   - Create upgrade branch
   - Generate change summary

Ensure production readiness before marking complete."""


class DeploymentAgent(BaseUpgradeAgent):
    """
    Agent responsible for deployment preparation.

    Responsibilities:
    - Validate final build
    - Create deployment artifacts
    - Commit changes to git
    - Generate upgrade report
    """

    def __init__(self, llm_config: LiteLLMConfig):
        config = AgentConfig(
            name="deployment_agent",
            description="Prepares application for production deployment",
            system_prompt=DEPLOYMENT_AGENT_PROMPT,
            max_iterations=3,
        )
        tools = [
            run_maven_build,
            commit_changes,
            create_branch,
            get_git_status,
        ]
        super().__init__(config, llm_config, tools)

    def run(self, state: UpgradeState) -> UpgradeState:
        """Execute deployment preparation."""
        state.current_agent = self.name
        state.phase = UpgradePhase.DEPLOYMENT_PREP
        state.add_agent_message(self.name, "Starting deployment preparation")

        project_path = state.project_info.project_path if state.project_info else "."

        # Step 1: Final build verification
        if not state.build_successful:
            state.add_agent_message(self.name, "Cannot prepare deployment: build not successful")
            return state

        # Step 2: Run final package build
        final_build = self._run_final_build(project_path)
        if not final_build:
            state.add_agent_message(self.name, "Final build failed")
            return state

        # Step 3: Generate upgrade report
        report = self._generate_upgrade_report(state)
        self._save_report(project_path, report)

        # Step 4: Commit changes if configured
        if state.upgrade_config.create_backup:
            self._commit_changes(state)

        # Step 5: Validate deployment readiness
        ready = self._validate_deployment_readiness(state)
        state.ready_for_deployment = ready

        if ready:
            state.phase = UpgradePhase.COMPLETED
            state.add_agent_message(self.name, "Application ready for deployment")
        else:
            state.add_agent_message(self.name, "Deployment validation failed - manual review required")

        return state

    def _run_final_build(self, project_path: str) -> bool:
        """Run final Maven build with package goal."""
        result = run_maven_build.invoke({
            "project_path": project_path,
            "goals": "clean package -DskipTests",
            "skip_tests": True,
        })
        return result.get("success", False)

    def _generate_upgrade_report(self, state: UpgradeState) -> str:
        """Generate a comprehensive upgrade report."""
        report_lines = [
            "# Java Upgrade Report",
            "",
            "## Summary",
            f"- **Status**: {'SUCCESS' if state.build_successful else 'FAILED'}",
            f"- **Target Java Version**: {state.upgrade_config.target_java_version}",
            f"- **Target Spring Boot Version**: {state.upgrade_config.target_spring_boot_version}",
            "",
            "## Changes Made",
            "",
            "### Source Code Changes",
        ]

        for change in state.code_changes[:50]:  # Limit to 50
            report_lines.append(f"- `{change.file_path}`: {change.description}")

        report_lines.extend([
            "",
            "### POM Changes",
        ])

        for change in state.pom_changes:
            report_lines.append(f"- {change.description}")

        report_lines.extend([
            "",
            "### Configuration Changes",
        ])

        for change in state.config_changes:
            report_lines.append(f"- `{change.file_path}`: {change.description}")

        report_lines.extend([
            "",
            "## Build Results",
            f"- **Total Build Attempts**: {state.total_build_attempts}",
            f"- **Final Status**: {'SUCCESS' if state.build_successful else 'FAILED'}",
        ])

        if state.test_results:
            report_lines.extend([
                "",
                "## Test Results",
                f"- **Total Tests**: {state.test_results.total_tests}",
                f"- **Passed**: {state.test_results.passed}",
                f"- **Failed**: {state.test_results.failed}",
                f"- **Errors**: {state.test_results.errors}",
                f"- **Skipped**: {state.test_results.skipped}",
            ])

        report_lines.extend([
            "",
            "## Dependencies Upgraded",
            f"- **Total Upgraded**: {state.total_dependencies_upgraded}",
        ])

        if state.migration_patterns:
            report_lines.extend([
                "",
                "## Migration Patterns Applied",
            ])
            for pattern in state.migration_patterns:
                report_lines.append(f"- **{pattern.get('type', 'Unknown')}**: {pattern.get('from', '')} -> {pattern.get('to', '')}")

        if state.requires_manual_intervention:
            report_lines.extend([
                "",
                "## Manual Intervention Required",
                f"- **Reason**: {state.manual_intervention_reason}",
                "",
                "### Unresolved Errors",
            ])
            for error in state.get_unresolved_errors():
                report_lines.append(f"- {error.error_type}: {error.message}")
                if error.suggested_fix:
                    report_lines.append(f"  - Suggested fix: {error.suggested_fix}")

        report_lines.extend([
            "",
            "## Deployment Checklist",
            "- [ ] Review all code changes",
            "- [ ] Verify database compatibility",
            "- [ ] Update configuration for production",
            "- [ ] Test in staging environment",
            "- [ ] Prepare rollback plan",
            "- [ ] Update monitoring dashboards",
            "",
            "---",
            f"*Report generated by Java Upgrade Workflow*",
        ])

        return "\n".join(report_lines)

    def _save_report(self, project_path: str, report: str) -> None:
        """Save the upgrade report to file."""
        report_path = Path(project_path) / "UPGRADE_REPORT.md"
        try:
            with open(report_path, "w") as f:
                f.write(report)
        except Exception:
            pass

    def _commit_changes(self, state: UpgradeState) -> None:
        """Commit all upgrade changes."""
        project_path = state.project_info.project_path if state.project_info else "."

        # Create commit message
        commit_msg = f"""[java-upgrade] Upgrade to Java {state.upgrade_config.target_java_version}

Changes:
- Upgraded Java version to {state.upgrade_config.target_java_version}
- Upgraded Spring Boot to {state.upgrade_config.target_spring_boot_version}
- Updated {state.total_dependencies_upgraded} dependencies
- Modified {state.total_files_modified} source files
- Resolved {state.total_errors_resolved} build errors

Migration patterns applied:
- javax to jakarta namespace migration
- JUnit 4 to JUnit 5 migration (if applicable)
- Spring Security configuration updates (if applicable)
"""

        result = commit_changes.invoke({
            "repo_path": project_path,
            "message": commit_msg,
        })

        if result.get("success"):
            state.add_agent_message(
                self.name,
                f"Changes committed: {result.get('commit_hash', 'unknown')}"
            )

    def _validate_deployment_readiness(self, state: UpgradeState) -> bool:
        """Validate that the application is ready for deployment."""
        # Check critical criteria
        if not state.build_successful:
            return False

        if state.requires_manual_intervention:
            return False

        if state.current_errors:
            return False

        # Check test results if tests were run
        if state.test_results:
            if state.test_results.failed > 0 or state.test_results.errors > 0:
                return False

        return True

    def get_deployment_artifacts(self, state: UpgradeState) -> list[str]:
        """Get list of deployment artifacts."""
        project_path = state.project_info.project_path if state.project_info else "."
        target_dir = Path(project_path) / "target"

        artifacts = []
        if target_dir.exists():
            for artifact in target_dir.glob("*.jar"):
                artifacts.append(str(artifact))
            for artifact in target_dir.glob("*.war"):
                artifacts.append(str(artifact))

        return artifacts
