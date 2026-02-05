"""
Build Agent

Handles Maven build execution and result analysis.
"""

import asyncio
from typing import Any

from java_upgrade_workflow.agents.base_agent import AgentConfig, BaseUpgradeAgent
from java_upgrade_workflow.config.litellm_config import LiteLLMConfig
from java_upgrade_workflow.state.upgrade_state import (
    BuildResult,
    ErrorInfo,
    TestResult,
    UpgradePhase,
    UpgradeState,
)
from java_upgrade_workflow.tools.maven_tools import (
    MavenTool,
    run_maven_build,
    run_maven_test,
)


BUILD_AGENT_PROMPT = """You are a Maven Build Expert.

Your role is to:
1. Execute Maven builds (clean, compile, test, package)
2. Analyze build output for errors and warnings
3. Categorize errors by type (compilation, dependency, test)
4. Provide actionable information for error resolution

When analyzing build failures:
- Identify the root cause
- Note the file and line number
- Suggest potential fixes
- Prioritize critical errors

Build phases:
1. clean - Remove target directory
2. compile - Compile source code
3. test - Run unit tests
4. package - Create JAR/WAR
5. install - Install to local repo
6. verify - Run integration tests

Report build status clearly and completely."""


class BuildAgent(BaseUpgradeAgent):
    """
    Agent responsible for Maven builds.

    Responsibilities:
    - Execute Maven builds
    - Parse and categorize errors
    - Run tests and report results
    - Validate build success
    """

    def __init__(self, llm_config: LiteLLMConfig):
        config = AgentConfig(
            name="build_agent",
            description="Executes and analyzes Maven builds",
            system_prompt=BUILD_AGENT_PROMPT,
            max_iterations=5,
        )
        tools = [run_maven_build, run_maven_test]
        super().__init__(config, llm_config, tools)
        self._maven_tool: MavenTool | None = None

    def run(self, state: UpgradeState) -> UpgradeState:
        """Execute build process."""
        state.current_agent = self.name
        state.phase = UpgradePhase.BUILD
        state.add_agent_message(self.name, "Starting Maven build")

        project_path = state.project_info.project_path if state.project_info else "."
        self._maven_tool = MavenTool(project_path)

        # Step 1: Clean and compile
        compile_result = self._run_compile(project_path)
        state.add_build_result(compile_result)

        if not compile_result.success:
            state.current_errors.extend(compile_result.errors)
            state.add_agent_message(
                self.name,
                f"Compilation failed with {len(compile_result.errors)} errors"
            )
            return state

        # Step 2: Run tests if configured
        if state.upgrade_config.run_tests:
            test_result = self._run_tests(project_path)
            state.add_build_result(test_result)

            if not test_result.success:
                state.current_errors.extend(test_result.errors)
                state.add_agent_message(
                    self.name,
                    f"Tests failed with {len(test_result.errors)} errors"
                )

                # Parse test results
                state.test_results = self._parse_test_results(test_result)
            else:
                state.tests_passed = True
                state.test_results = self._parse_test_results(test_result)
        else:
            state.tests_passed = True

        # Step 3: Package if compilation and tests passed
        if state.build_successful and state.tests_passed:
            package_result = self._run_package(project_path)
            state.add_build_result(package_result)

            if package_result.success:
                state.add_agent_message(self.name, "Build and package successful")
            else:
                state.current_errors.extend(package_result.errors)

        return state

    def _run_compile(self, project_path: str) -> BuildResult:
        """Run Maven clean compile."""
        result = run_maven_build.invoke({
            "project_path": project_path,
            "goals": "clean compile",
            "skip_tests": True,
        })

        errors = [
            ErrorInfo(**e) if isinstance(e, dict) else e
            for e in result.get("errors", [])
        ]

        return BuildResult(
            success=result.get("success", False),
            phase="compile",
            duration_seconds=result.get("duration", 0),
            output=result.get("output_preview", ""),
            errors=errors,
            warnings=result.get("warnings", []),
        )

    def _run_tests(self, project_path: str) -> BuildResult:
        """Run Maven test."""
        result = run_maven_test.invoke({
            "project_path": project_path,
        })

        errors = []
        if not result.get("success", False):
            errors.append(ErrorInfo(
                error_type="test",
                message=f"Tests failed: {result.get('failures', 0)} failures, {result.get('errors', 0)} errors",
            ))

        return BuildResult(
            success=result.get("success", False),
            phase="test",
            duration_seconds=result.get("duration", 0),
            output=result.get("output_preview", ""),
            errors=errors,
        )

    def _run_package(self, project_path: str) -> BuildResult:
        """Run Maven package."""
        result = run_maven_build.invoke({
            "project_path": project_path,
            "goals": "package",
            "skip_tests": True,
        })

        errors = [
            ErrorInfo(**e) if isinstance(e, dict) else e
            for e in result.get("errors", [])
        ]

        return BuildResult(
            success=result.get("success", False),
            phase="package",
            duration_seconds=result.get("duration", 0),
            output=result.get("output_preview", ""),
            errors=errors,
        )

    def _parse_test_results(self, build_result: BuildResult) -> TestResult:
        """Parse test results from build output."""
        import re

        output = build_result.output

        # Parse test summary
        total = 0
        passed = 0
        failed = 0
        errors = 0
        skipped = 0

        # Pattern: Tests run: X, Failures: Y, Errors: Z, Skipped: W
        summary_match = re.search(
            r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)",
            output
        )

        if summary_match:
            total = int(summary_match.group(1))
            failed = int(summary_match.group(2))
            errors = int(summary_match.group(3))
            skipped = int(summary_match.group(4))
            passed = total - failed - errors - skipped

        # Find failed test names
        failed_tests = []
        failed_pattern = re.findall(r"(\w+(?:\.\w+)*)\s+Time elapsed:.*<<<\s*FAILURE!", output)
        failed_tests.extend(failed_pattern)

        error_tests = []
        error_pattern = re.findall(r"(\w+(?:\.\w+)*)\s+Time elapsed:.*<<<\s*ERROR!", output)
        error_tests.extend(error_pattern)

        return TestResult(
            total_tests=total,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            duration_seconds=build_result.duration_seconds,
            failed_tests=failed_tests,
            error_tests=error_tests,
        )

    def run_incremental_build(self, state: UpgradeState) -> BuildResult:
        """Run incremental build without clean."""
        project_path = state.project_info.project_path if state.project_info else "."

        result = run_maven_build.invoke({
            "project_path": project_path,
            "goals": "compile",
            "skip_tests": True,
        })

        errors = [
            ErrorInfo(**e) if isinstance(e, dict) else e
            for e in result.get("errors", [])
        ]

        return BuildResult(
            success=result.get("success", False),
            phase="compile",
            duration_seconds=result.get("duration", 0),
            output=result.get("output_preview", ""),
            errors=errors,
        )
