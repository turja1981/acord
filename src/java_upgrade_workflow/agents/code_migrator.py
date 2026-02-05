"""
Code Migrator Agent

Handles source code migrations including:
- javax to jakarta namespace migration
- JUnit 4 to JUnit 5 migration
- Deprecated API replacements
- Spring configuration updates
"""

import re
from pathlib import Path
from typing import Any, Optional

from java_upgrade_workflow.agents.base_agent import AgentConfig, BaseUpgradeAgent
from java_upgrade_workflow.config.litellm_config import LiteLLMConfig
from java_upgrade_workflow.state.upgrade_state import (
    CodeChange,
    UpgradePhase,
    UpgradeState,
)
from java_upgrade_workflow.tools.code_tools import (
    read_java_file,
    write_java_file,
    apply_code_fix,
    search_code_pattern,
)


CODE_MIGRATOR_PROMPT = """You are a Java Code Migration Expert.

Your role is to migrate Java/Spring Boot code for version upgrades:

1. Namespace Migrations (javax -> jakarta):
   - javax.persistence.* -> jakarta.persistence.*
   - javax.servlet.* -> jakarta.servlet.*
   - javax.validation.* -> jakarta.validation.*
   - javax.annotation.* -> jakarta.annotation.*
   - javax.inject.* -> jakarta.inject.*

2. JUnit 4 to JUnit 5:
   - @org.junit.Test -> @org.junit.jupiter.api.Test
   - @Before -> @BeforeEach
   - @After -> @AfterEach
   - @BeforeClass -> @BeforeAll (+ static)
   - @AfterClass -> @AfterAll (+ static)
   - @Ignore -> @Disabled
   - Assert.* -> Assertions.*

3. Spring Security (for deprecated patterns):
   - Replace WebSecurityConfigurerAdapter with SecurityFilterChain bean
   - Update antMatchers to requestMatchers
   - Handle authorizeRequests -> authorizeHttpRequests

4. Property Files:
   - spring.redis.* -> spring.data.redis.*
   - Actuator endpoint changes

Always maintain code functionality and handle edge cases properly."""


# Migration patterns with regex
MIGRATION_PATTERNS = {
    # javax to jakarta
    "javax_persistence": {
        "find": r"import\s+javax\.persistence\.",
        "replace": "import jakarta.persistence.",
        "file_pattern": "*.java",
    },
    "javax_servlet": {
        "find": r"import\s+javax\.servlet\.",
        "replace": "import jakarta.servlet.",
        "file_pattern": "*.java",
    },
    "javax_validation": {
        "find": r"import\s+javax\.validation\.",
        "replace": "import jakarta.validation.",
        "file_pattern": "*.java",
    },
    "javax_annotation": {
        "find": r"import\s+javax\.annotation\.",
        "replace": "import jakarta.annotation.",
        "file_pattern": "*.java",
    },
    "javax_inject": {
        "find": r"import\s+javax\.inject\.",
        "replace": "import jakarta.inject.",
        "file_pattern": "*.java",
    },
    "javax_ws": {
        "find": r"import\s+javax\.ws\.",
        "replace": "import jakarta.ws.",
        "file_pattern": "*.java",
    },
    "javax_xml_bind": {
        "find": r"import\s+javax\.xml\.bind\.",
        "replace": "import jakarta.xml.bind.",
        "file_pattern": "*.java",
    },
    # JUnit 4 to JUnit 5
    "junit_test": {
        "find": r"import\s+org\.junit\.Test;",
        "replace": "import org.junit.jupiter.api.Test;",
        "file_pattern": "*Test.java",
    },
    "junit_before": {
        "find": r"import\s+org\.junit\.Before;",
        "replace": "import org.junit.jupiter.api.BeforeEach;",
        "file_pattern": "*Test.java",
    },
    "junit_after": {
        "find": r"import\s+org\.junit\.After;",
        "replace": "import org.junit.jupiter.api.AfterEach;",
        "file_pattern": "*Test.java",
    },
    "junit_beforeclass": {
        "find": r"import\s+org\.junit\.BeforeClass;",
        "replace": "import org.junit.jupiter.api.BeforeAll;",
        "file_pattern": "*Test.java",
    },
    "junit_afterclass": {
        "find": r"import\s+org\.junit\.AfterClass;",
        "replace": "import org.junit.jupiter.api.AfterAll;",
        "file_pattern": "*Test.java",
    },
    "junit_ignore": {
        "find": r"import\s+org\.junit\.Ignore;",
        "replace": "import org.junit.jupiter.api.Disabled;",
        "file_pattern": "*Test.java",
    },
    "junit_assert": {
        "find": r"import\s+org\.junit\.Assert;",
        "replace": "import org.junit.jupiter.api.Assertions;",
        "file_pattern": "*Test.java",
    },
    "junit_runwith": {
        "find": r"import\s+org\.junit\.runner\.RunWith;",
        "replace": "import org.junit.jupiter.api.extension.ExtendWith;",
        "file_pattern": "*Test.java",
    },
}

# Annotation replacements
ANNOTATION_REPLACEMENTS = {
    "@Before": "@BeforeEach",
    "@After": "@AfterEach",
    "@BeforeClass": "@BeforeAll",
    "@AfterClass": "@AfterAll",
    "@Ignore": "@Disabled",
    "@RunWith": "@ExtendWith",
    "Assert.assertEquals": "Assertions.assertEquals",
    "Assert.assertTrue": "Assertions.assertTrue",
    "Assert.assertFalse": "Assertions.assertFalse",
    "Assert.assertNull": "Assertions.assertNull",
    "Assert.assertNotNull": "Assertions.assertNotNull",
    "Assert.assertThrows": "Assertions.assertThrows",
    "Assert.fail": "Assertions.fail",
}


class CodeMigratorAgent(BaseUpgradeAgent):
    """
    Agent responsible for migrating source code.

    Responsibilities:
    - Apply namespace migrations
    - Update deprecated APIs
    - Migrate test frameworks
    - Update configuration files
    """

    def __init__(self, llm_config: LiteLLMConfig):
        config = AgentConfig(
            name="code_migrator",
            description="Migrates Java source code for upgrade compatibility",
            system_prompt=CODE_MIGRATOR_PROMPT,
            max_iterations=10,
        )
        tools = [
            read_java_file,
            write_java_file,
            apply_code_fix,
            search_code_pattern,
        ]
        super().__init__(config, llm_config, tools)

    def run(self, state: UpgradeState) -> UpgradeState:
        """Execute code migration process."""
        state.current_agent = self.name
        state.phase = UpgradePhase.CODE_MIGRATION
        state.add_agent_message(self.name, "Starting code migration")

        project_path = state.project_info.project_path if state.project_info else "."

        # Step 1: Apply automated migrations to source files
        for file_path in state.source_files:
            changes = self._migrate_file(file_path, is_test=False)
            state.code_changes.extend(changes)

        # Step 2: Apply migrations to test files
        for file_path in state.test_files:
            changes = self._migrate_file(file_path, is_test=True)
            state.code_changes.extend(changes)

        # Step 3: Handle complex migrations using LLM
        complex_patterns = self._identify_complex_migrations(state)
        for pattern in complex_patterns:
            self._handle_complex_migration(state, pattern)

        # Step 4: Update property files
        self._migrate_property_files(project_path, state)

        state.add_agent_message(
            self.name,
            f"Code migration complete. Modified {len(state.code_changes)} files."
        )
        state.code_migrated = True

        return state

    def _migrate_file(self, file_path: str, is_test: bool = False) -> list[CodeChange]:
        """Apply migrations to a single file."""
        changes = []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return changes

        original_content = content
        modified = False

        # Apply import migrations
        for pattern_name, pattern_info in MIGRATION_PATTERNS.items():
            # Skip test-specific patterns for non-test files
            if "Test.java" in pattern_info.get("file_pattern", "") and not is_test:
                continue

            # Apply the migration
            find_pattern = pattern_info["find"]
            replace_pattern = pattern_info["replace"]

            if re.search(find_pattern, content):
                content = re.sub(find_pattern, replace_pattern, content)
                modified = True

        # Apply annotation replacements
        for old, new in ANNOTATION_REPLACEMENTS.items():
            if old in content:
                content = content.replace(old, new)
                modified = True

        if modified:
            # Write the modified content
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)

                changes.append(CodeChange(
                    file_path=file_path,
                    change_type="modify",
                    description="Applied automated migrations",
                    old_content=original_content[:500],  # Store sample
                    new_content=content[:500],
                    agent=self.name,
                ))
            except Exception:
                pass

        return changes

    def _identify_complex_migrations(self, state: UpgradeState) -> list[dict[str, Any]]:
        """Identify migrations that need LLM assistance."""
        complex_patterns = []

        # Check for WebSecurityConfigurerAdapter
        security_pattern = next(
            (p for p in state.deprecated_apis if "websecurityconfigureradapter" in p.get("name", "").lower()),
            None
        )
        if security_pattern:
            complex_patterns.append({
                "type": "spring_security",
                "description": "WebSecurityConfigurerAdapter to SecurityFilterChain migration",
                "locations": security_pattern.get("sample_locations", []),
            })

        return complex_patterns

    def _handle_complex_migration(self, state: UpgradeState, pattern: dict[str, Any]) -> None:
        """Use LLM to handle complex migration patterns."""
        if pattern["type"] == "spring_security":
            for location in pattern.get("locations", [])[:3]:  # Limit to 3 files
                file_path = location.get("file")
                if file_path:
                    self._migrate_spring_security(file_path, state)

    def _migrate_spring_security(self, file_path: str, state: UpgradeState) -> None:
        """Migrate Spring Security configuration using LLM assistance."""
        result = read_java_file.invoke({"file_path": file_path})
        if not result.get("success"):
            return

        content = result.get("content", "")

        # Ask LLM to help with migration
        message = f"""Migrate this Spring Security configuration from WebSecurityConfigurerAdapter to the new SecurityFilterChain approach:

```java
{content}
```

Provide the complete migrated code. Key changes needed:
1. Remove 'extends WebSecurityConfigurerAdapter'
2. Replace @Override configure methods with @Bean SecurityFilterChain methods
3. Update antMatchers to requestMatchers
4. Update authorizeRequests to authorizeHttpRequests
5. Maintain same security rules and functionality"""

        messages = self._build_messages(state, message)
        response = self._call_llm_sync(messages, use_tools=False)

        if response.get("success") and response.get("content"):
            # Extract code from response
            migrated_code = self._extract_code_block(response.get("content", ""))
            if migrated_code:
                write_java_file.invoke({
                    "file_path": file_path,
                    "content": migrated_code,
                })
                state.code_changes.append(CodeChange(
                    file_path=file_path,
                    change_type="modify",
                    description="Migrated Spring Security configuration",
                    agent=self.name,
                ))

    def _extract_code_block(self, text: str) -> Optional[str]:
        """Extract Java code block from LLM response."""
        # Look for code block markers
        java_pattern = r"```java\n([\s\S]*?)```"
        match = re.search(java_pattern, text)
        if match:
            return match.group(1).strip()

        # Try without language specifier
        code_pattern = r"```\n([\s\S]*?)```"
        match = re.search(code_pattern, text)
        if match:
            return match.group(1).strip()

        return None

    def _migrate_property_files(self, project_path: str, state: UpgradeState) -> None:
        """Migrate application property files."""
        property_files = [
            "src/main/resources/application.properties",
            "src/main/resources/application.yml",
            "src/main/resources/application.yaml",
        ]

        property_migrations = {
            # Spring Data Redis
            "spring.redis.": "spring.data.redis.",
            # Actuator
            "management.metrics.export.": "management.prometheus.",
            # Server
            "server.max-http-header-size": "server.max-http-request-header-size",
        }

        for prop_file in property_files:
            full_path = Path(project_path) / prop_file
            if full_path.exists():
                try:
                    with open(full_path, "r") as f:
                        content = f.read()

                    original = content
                    for old, new in property_migrations.items():
                        content = content.replace(old, new)

                    if content != original:
                        with open(full_path, "w") as f:
                            f.write(content)

                        state.config_changes.append(CodeChange(
                            file_path=str(full_path),
                            change_type="modify",
                            description="Updated property keys for Spring Boot 3",
                            agent=self.name,
                        ))
                except Exception:
                    pass
