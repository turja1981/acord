"""
Code Analyzer Agent

Analyzes Java/Spring Boot codebase to identify upgrade requirements,
deprecated APIs, and migration patterns.
"""

from typing import Any

from java_upgrade_workflow.agents.base_agent import AgentConfig, BaseUpgradeAgent
from java_upgrade_workflow.config.litellm_config import LiteLLMConfig
from java_upgrade_workflow.state.upgrade_state import (
    ProjectInfo,
    UpgradePhase,
    UpgradeState,
)
from java_upgrade_workflow.tools.code_tools import (
    CodeAnalysisTool,
    find_java_files,
    read_java_file,
    search_code_pattern,
    analyze_java_file_for_upgrade,
)
from java_upgrade_workflow.tools.maven_tools import analyze_pom


CODE_ANALYZER_PROMPT = """You are a Java/Spring Boot Code Analysis Expert.

Your role is to analyze Java codebases to identify:
1. Current Java version and Spring Boot version
2. Dependencies that need upgrading
3. Deprecated APIs and patterns that need migration
4. Compatibility issues with target Java/Spring Boot versions
5. Code patterns that may cause issues during upgrade

Key analysis areas:
- javax.* to jakarta.* namespace migrations (required for Jakarta EE 9+/Spring Boot 3)
- JUnit 4 to JUnit 5 migrations
- WebSecurityConfigurerAdapter deprecation (Spring Security 5.7+)
- Spring configuration changes
- Property file changes for Spring Boot 3

Output your analysis in a structured format identifying:
- Files that need modification
- Specific patterns to change
- Priority of changes (critical, high, medium, low)
- Estimated complexity of each change

Be thorough but efficient. Focus on actionable findings."""


class CodeAnalyzerAgent(BaseUpgradeAgent):
    """
    Agent responsible for analyzing the codebase before upgrade.

    Responsibilities:
    - Parse and analyze pom.xml
    - Scan Java source files for deprecated patterns
    - Identify migration requirements
    - Create prioritized list of changes needed
    """

    def __init__(self, llm_config: LiteLLMConfig):
        config = AgentConfig(
            name="code_analyzer",
            description="Analyzes Java codebase for upgrade requirements",
            system_prompt=CODE_ANALYZER_PROMPT,
            max_iterations=3,
        )
        tools = [
            find_java_files,
            read_java_file,
            search_code_pattern,
            analyze_pom,
            analyze_java_file_for_upgrade,
        ]
        super().__init__(config, llm_config, tools)

    def run(self, state: UpgradeState) -> UpgradeState:
        """Analyze the project and update state with findings."""
        state.current_agent = self.name
        state.phase = UpgradePhase.ANALYSIS
        state.add_agent_message(self.name, "Starting code analysis")

        # Step 1: Analyze POM
        pom_path = f"{state.project_info.project_path}/pom.xml" if state.project_info else "./pom.xml"
        pom_result = analyze_pom.invoke({"pom_path": pom_path})

        if pom_result.get("success"):
            # Update project info from POM analysis
            if state.project_info is None:
                state.project_info = ProjectInfo(project_path=".")

            state.project_info.current_java_version = pom_result.get("java_version")
            state.project_info.current_spring_boot_version = pom_result.get("spring_boot_version")

            project_info = pom_result.get("project_info", {})
            state.project_info.group_id = project_info.get("group_id")
            state.project_info.artifact_id = project_info.get("artifact_id")
            state.project_info.packaging = project_info.get("packaging", "jar")

            # Store dependencies
            for dep in pom_result.get("dependencies", []):
                from java_upgrade_workflow.state.upgrade_state import DependencyInfo
                state.dependencies.append(DependencyInfo(**dep))

        # Step 2: Find all Java files
        project_path = state.project_info.project_path if state.project_info else "."
        files_result = find_java_files.invoke({
            "project_path": project_path,
            "exclude_tests": False,
        })

        if files_result.get("success"):
            all_files = files_result.get("files", [])
            state.source_files = [f for f in all_files if "/test/" not in f]
            state.test_files = [f for f in all_files if "/test/" in f]

        # Step 3: Search for deprecated patterns
        deprecated_patterns = self._find_deprecated_patterns(project_path)
        state.deprecated_apis = deprecated_patterns

        # Step 4: Identify migration patterns
        migration_patterns = self._identify_migration_patterns(state)
        state.migration_patterns = migration_patterns

        # Step 5: Use LLM to analyze and prioritize
        analysis_summary = self._llm_analyze(state)
        state.add_agent_message(
            self.name,
            f"Analysis complete. Found {len(state.deprecated_apis)} deprecated patterns, "
            f"{len(state.source_files)} source files, {len(state.dependencies)} dependencies."
        )

        state.analysis_complete = True
        return state

    def _find_deprecated_patterns(self, project_path: str) -> list[dict[str, Any]]:
        """Search for deprecated patterns in the codebase."""
        patterns_to_check = [
            {
                "name": "javax_imports",
                "pattern": r"import\s+javax\.(persistence|servlet|validation|annotation|inject|ws)",
                "severity": "critical",
                "description": "javax.* imports need migration to jakarta.*",
            },
            {
                "name": "websecurityconfigureradapter",
                "pattern": r"extends\s+WebSecurityConfigurerAdapter",
                "severity": "high",
                "description": "WebSecurityConfigurerAdapter is deprecated",
            },
            {
                "name": "junit4",
                "pattern": r"import\s+org\.junit\.(Test|Before|After)",
                "severity": "medium",
                "description": "JUnit 4 should be migrated to JUnit 5",
            },
            {
                "name": "springfox",
                "pattern": r"import\s+springfox\.",
                "severity": "high",
                "description": "Springfox not compatible with Spring Boot 3",
            },
            {
                "name": "hibernate_validator",
                "pattern": r"import\s+org\.hibernate\.validator\.constraints\.(NotEmpty|NotBlank)",
                "severity": "medium",
                "description": "Check Hibernate Validator constraints compatibility",
            },
        ]

        found_patterns = []

        for pattern_info in patterns_to_check:
            result = search_code_pattern.invoke({
                "project_path": project_path,
                "pattern": pattern_info["pattern"],
                "max_results": 100,
            })

            if result.get("success") and result.get("total_matches", 0) > 0:
                found_patterns.append({
                    "name": pattern_info["name"],
                    "severity": pattern_info["severity"],
                    "description": pattern_info["description"],
                    "occurrences": result.get("total_matches"),
                    "sample_locations": result.get("matches", [])[:5],
                })

        return found_patterns

    def _identify_migration_patterns(self, state: UpgradeState) -> list[dict[str, Any]]:
        """Identify specific migration patterns needed."""
        migrations = []

        # Check if javax to jakarta migration is needed
        javax_pattern = next(
            (p for p in state.deprecated_apis if p["name"] == "javax_imports"),
            None
        )
        if javax_pattern:
            migrations.append({
                "type": "namespace_migration",
                "from": "javax.*",
                "to": "jakarta.*",
                "priority": "critical",
                "auto_fixable": True,
                "affected_files": javax_pattern.get("occurrences", 0),
            })

        # Check Spring Boot version jump
        if state.project_info and state.project_info.current_spring_boot_version:
            current = state.project_info.current_spring_boot_version
            target = state.upgrade_config.target_spring_boot_version

            if current.startswith("2.") and target.startswith("3."):
                migrations.append({
                    "type": "spring_boot_major_upgrade",
                    "from": current,
                    "to": target,
                    "priority": "critical",
                    "auto_fixable": False,
                    "notes": "Major version upgrade requires careful review",
                })

        # Check for JUnit migration
        junit_pattern = next(
            (p for p in state.deprecated_apis if p["name"] == "junit4"),
            None
        )
        if junit_pattern:
            migrations.append({
                "type": "junit_migration",
                "from": "JUnit 4",
                "to": "JUnit 5",
                "priority": "medium",
                "auto_fixable": True,
                "affected_files": junit_pattern.get("occurrences", 0),
            })

        return migrations

    def _llm_analyze(self, state: UpgradeState) -> str:
        """Use LLM to provide analysis summary."""
        analysis_data = {
            "java_version": state.project_info.current_java_version if state.project_info else "unknown",
            "spring_boot_version": state.project_info.current_spring_boot_version if state.project_info else None,
            "total_source_files": len(state.source_files),
            "total_test_files": len(state.test_files),
            "deprecated_patterns": state.deprecated_apis,
            "migration_patterns": state.migration_patterns,
            "dependencies_count": len(state.dependencies),
        }

        message = f"""Analyze this Java project upgrade scenario and provide a summary:

{analysis_data}

Target versions:
- Java: {state.upgrade_config.target_java_version}
- Spring Boot: {state.upgrade_config.target_spring_boot_version}

Provide:
1. Overall complexity assessment (low/medium/high)
2. Key risks
3. Recommended upgrade order
4. Any manual intervention likely needed"""

        messages = self._build_messages(state, message)
        response = self._call_llm_sync(messages, use_tools=False)

        if response.get("success"):
            return response.get("content", "")
        return "Analysis completed with limited LLM assistance."
