"""
Dependency Upgrader Agent

Handles upgrading Maven dependencies including Java version,
Spring Boot version, and all related dependencies.
"""

import re
from typing import Any, Optional

from java_upgrade_workflow.agents.base_agent import AgentConfig, BaseUpgradeAgent
from java_upgrade_workflow.config.litellm_config import LiteLLMConfig
from java_upgrade_workflow.state.upgrade_state import (
    CodeChange,
    DependencyInfo,
    UpgradePhase,
    UpgradeState,
)
from java_upgrade_workflow.tools.maven_tools import analyze_pom, update_dependency
from java_upgrade_workflow.tools.code_tools import read_java_file, write_java_file


DEPENDENCY_UPGRADER_PROMPT = """You are a Maven Dependency Upgrade Expert.

Your role is to upgrade Java project dependencies safely and correctly:

1. Java Version Upgrade:
   - Update maven-compiler-plugin source/target
   - Update java.version property
   - Ensure compiler plugin version supports new Java

2. Spring Boot Upgrade (2.x to 3.x requires):
   - Update parent POM version
   - Update spring-boot-starter versions
   - Replace javax.* with jakarta.* dependencies
   - Update compatible versions for all Spring ecosystem libraries

3. Dependency Compatibility:
   - Check and update third-party library versions
   - Ensure all dependencies work with new Java/Spring versions
   - Handle transitive dependency conflicts

Key dependency mappings for Spring Boot 3:
- javax.persistence-api -> jakarta.persistence-api 3.1.0
- javax.servlet-api -> jakarta.servlet-api 6.0.0
- javax.validation-api -> jakarta.validation-api 3.0.2
- springfox -> springdoc-openapi-starter-webmvc-ui 2.x

Always provide specific version numbers and explain the reasoning for each change."""


# Dependency version mappings for common upgrades
SPRING_BOOT_3_DEPS = {
    "org.springframework.boot:spring-boot-starter-parent": "3.2.0",
    "org.springframework.boot:spring-boot-dependencies": "3.2.0",
    "org.springframework.cloud:spring-cloud-dependencies": "2023.0.0",
    "jakarta.persistence:jakarta.persistence-api": "3.1.0",
    "jakarta.servlet:jakarta.servlet-api": "6.0.0",
    "jakarta.validation:jakarta.validation-api": "3.0.2",
    "org.springdoc:springdoc-openapi-starter-webmvc-ui": "2.3.0",
}

JAVA_21_COMPATIBLE_DEPS = {
    "org.projectlombok:lombok": "1.18.30",
    "org.mapstruct:mapstruct": "1.5.5.Final",
    "com.google.guava:guava": "33.0.0-jre",
    "org.apache.commons:commons-lang3": "3.14.0",
}


class DependencyUpgraderAgent(BaseUpgradeAgent):
    """
    Agent responsible for upgrading Maven dependencies.

    Responsibilities:
    - Upgrade Java version in POM
    - Upgrade Spring Boot version
    - Update all dependent libraries
    - Handle javax to jakarta migrations in dependencies
    """

    def __init__(self, llm_config: LiteLLMConfig):
        config = AgentConfig(
            name="dependency_upgrader",
            description="Upgrades Maven dependencies for Java/Spring Boot upgrade",
            system_prompt=DEPENDENCY_UPGRADER_PROMPT,
            max_iterations=5,
        )
        tools = [
            analyze_pom,
            update_dependency,
            read_java_file,
            write_java_file,
        ]
        super().__init__(config, llm_config, tools)

    def run(self, state: UpgradeState) -> UpgradeState:
        """Execute dependency upgrade process."""
        state.current_agent = self.name
        state.phase = UpgradePhase.DEPENDENCY_UPGRADE
        state.add_agent_message(self.name, "Starting dependency upgrade")

        pom_path = f"{state.project_info.project_path}/pom.xml" if state.project_info else "./pom.xml"

        # Step 1: Read current POM
        pom_content = self._read_pom(pom_path)
        if not pom_content:
            state.add_agent_message(self.name, "ERROR: Could not read pom.xml")
            return state

        # Step 2: Upgrade Java version
        pom_content, java_changed = self._upgrade_java_version(
            pom_content,
            state.upgrade_config.target_java_version
        )
        if java_changed:
            state.pom_changes.append(CodeChange(
                file_path=pom_path,
                change_type="modify",
                description=f"Upgraded Java version to {state.upgrade_config.target_java_version}",
                agent=self.name,
            ))

        # Step 3: Upgrade Spring Boot version
        if state.project_info and state.project_info.current_spring_boot_version:
            pom_content, spring_changed = self._upgrade_spring_boot(
                pom_content,
                state.upgrade_config.target_spring_boot_version
            )
            if spring_changed:
                state.pom_changes.append(CodeChange(
                    file_path=pom_path,
                    change_type="modify",
                    description=f"Upgraded Spring Boot to {state.upgrade_config.target_spring_boot_version}",
                    agent=self.name,
                ))

        # Step 4: Update individual dependencies
        for dep in state.dependencies:
            pom_content, updated = self._upgrade_dependency(pom_content, dep)
            if updated:
                state.total_dependencies_upgraded += 1
                dep.target_version = updated

        # Step 5: Add missing Jakarta dependencies if needed
        if self._needs_jakarta_migration(state):
            pom_content = self._add_jakarta_dependencies(pom_content)

        # Step 6: Write updated POM
        self._write_pom(pom_path, pom_content)

        state.add_agent_message(
            self.name,
            f"Dependency upgrade complete. Updated {state.total_dependencies_upgraded} dependencies."
        )
        state.dependencies_upgraded = True

        return state

    def _read_pom(self, pom_path: str) -> Optional[str]:
        """Read POM file content."""
        try:
            with open(pom_path, "r") as f:
                return f.read()
        except Exception:
            return None

    def _write_pom(self, pom_path: str, content: str) -> bool:
        """Write POM file content."""
        try:
            # Backup original
            with open(pom_path + ".bak", "w") as f:
                with open(pom_path, "r") as original:
                    f.write(original.read())

            with open(pom_path, "w") as f:
                f.write(content)
            return True
        except Exception:
            return False

    def _upgrade_java_version(
        self,
        pom_content: str,
        target_version: str
    ) -> tuple[str, bool]:
        """Upgrade Java version in POM."""
        changed = False

        # Update java.version property
        java_version_pattern = r"(<java\.version>)[^<]+(</java\.version>)"
        if re.search(java_version_pattern, pom_content):
            pom_content = re.sub(
                java_version_pattern,
                rf"\g<1>{target_version}\g<2>",
                pom_content
            )
            changed = True
        else:
            # Add java.version property if not exists
            properties_pattern = r"(<properties>)"
            if re.search(properties_pattern, pom_content):
                pom_content = re.sub(
                    properties_pattern,
                    rf"\g<1>\n        <java.version>{target_version}</java.version>",
                    pom_content
                )
                changed = True

        # Update maven.compiler.source/target
        for prop in ["maven.compiler.source", "maven.compiler.target"]:
            pattern = rf"(<{prop}>)[^<]+(</{prop}>)"
            if re.search(pattern, pom_content):
                pom_content = re.sub(pattern, rf"\g<1>{target_version}\g<2>", pom_content)
                changed = True

        # Update maven-compiler-plugin configuration
        compiler_source_pattern = r"(<configuration>[\s\S]*?<source>)[^<]+(</source>)"
        pom_content = re.sub(
            compiler_source_pattern,
            rf"\g<1>{target_version}\g<2>",
            pom_content
        )

        compiler_target_pattern = r"(<configuration>[\s\S]*?<target>)[^<]+(</target>)"
        pom_content = re.sub(
            compiler_target_pattern,
            rf"\g<1>{target_version}\g<2>",
            pom_content
        )

        return pom_content, changed

    def _upgrade_spring_boot(
        self,
        pom_content: str,
        target_version: str
    ) -> tuple[str, bool]:
        """Upgrade Spring Boot version in POM."""
        changed = False

        # Update parent version if using spring-boot-starter-parent
        parent_pattern = (
            r"(<parent>[\s\S]*?<artifactId>spring-boot-starter-parent</artifactId>[\s\S]*?"
            r"<version>)[^<]+(</version>[\s\S]*?</parent>)"
        )
        if re.search(parent_pattern, pom_content):
            pom_content = re.sub(parent_pattern, rf"\g<1>{target_version}\g<2>", pom_content)
            changed = True

        # Update spring-boot.version property if exists
        spring_version_pattern = r"(<spring-boot\.version>)[^<]+(</spring-boot\.version>)"
        if re.search(spring_version_pattern, pom_content):
            pom_content = re.sub(
                spring_version_pattern,
                rf"\g<1>{target_version}\g<2>",
                pom_content
            )
            changed = True

        return pom_content, changed

    def _upgrade_dependency(
        self,
        pom_content: str,
        dep: DependencyInfo
    ) -> tuple[str, Optional[str]]:
        """Upgrade a single dependency if needed."""
        full_name = f"{dep.group_id}:{dep.artifact_id}"

        # Check if we have a known upgrade target
        target_version = None

        # Check Spring Boot 3 compatible versions
        if full_name in SPRING_BOOT_3_DEPS:
            target_version = SPRING_BOOT_3_DEPS[full_name]
        elif full_name in JAVA_21_COMPATIBLE_DEPS:
            target_version = JAVA_21_COMPATIBLE_DEPS[full_name]

        # Handle javax to jakarta migration
        if dep.group_id.startswith("javax."):
            jakarta_group = dep.group_id.replace("javax.", "jakarta.")
            jakarta_full = f"{jakarta_group}:{dep.artifact_id}"
            if jakarta_full in SPRING_BOOT_3_DEPS:
                # Need to replace the entire dependency
                target_version = SPRING_BOOT_3_DEPS[jakarta_full]
                pom_content = self._replace_javax_with_jakarta(
                    pom_content, dep, jakarta_group, target_version
                )
                return pom_content, target_version

        if target_version and target_version != dep.current_version:
            # Update the version
            pattern = re.compile(
                rf"(<dependency>\s*"
                rf"<groupId>{re.escape(dep.group_id)}</groupId>\s*"
                rf"<artifactId>{re.escape(dep.artifact_id)}</artifactId>\s*"
                rf"<version>)[^<]+(</version>)",
                re.DOTALL
            )
            pom_content = pattern.sub(rf"\g<1>{target_version}\g<2>", pom_content)
            return pom_content, target_version

        return pom_content, None

    def _replace_javax_with_jakarta(
        self,
        pom_content: str,
        dep: DependencyInfo,
        jakarta_group: str,
        target_version: str
    ) -> str:
        """Replace javax dependency with jakarta equivalent."""
        # Find and replace the entire dependency block
        pattern = re.compile(
            rf"<dependency>\s*"
            rf"<groupId>{re.escape(dep.group_id)}</groupId>\s*"
            rf"<artifactId>{re.escape(dep.artifact_id)}</artifactId>\s*"
            rf"(<version>[^<]+</version>\s*)?"
            rf"(<scope>[^<]+</scope>\s*)?"
            rf"</dependency>",
            re.DOTALL
        )

        jakarta_dep = f"""<dependency>
            <groupId>{jakarta_group}</groupId>
            <artifactId>{dep.artifact_id}</artifactId>
            <version>{target_version}</version>
        </dependency>"""

        return pattern.sub(jakarta_dep, pom_content)

    def _needs_jakarta_migration(self, state: UpgradeState) -> bool:
        """Check if project needs javax to jakarta migration."""
        for pattern in state.deprecated_apis:
            if pattern.get("name") == "javax_imports":
                return True
        return False

    def _add_jakarta_dependencies(self, pom_content: str) -> str:
        """Add Jakarta API dependencies to POM."""
        jakarta_deps = """
        <!-- Jakarta API Dependencies for Spring Boot 3 -->
        <dependency>
            <groupId>jakarta.persistence</groupId>
            <artifactId>jakarta.persistence-api</artifactId>
            <version>3.1.0</version>
        </dependency>
        <dependency>
            <groupId>jakarta.validation</groupId>
            <artifactId>jakarta.validation-api</artifactId>
            <version>3.0.2</version>
        </dependency>
        <dependency>
            <groupId>jakarta.servlet</groupId>
            <artifactId>jakarta.servlet-api</artifactId>
            <version>6.0.0</version>
            <scope>provided</scope>
        </dependency>
"""
        # Find dependencies section and add Jakarta deps
        deps_pattern = r"(</dependencies>)"
        pom_content = re.sub(
            deps_pattern,
            jakarta_deps + r"\n    \g<1>",
            pom_content,
            count=1
        )

        return pom_content
