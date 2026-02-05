"""
Maven Build Tools

Tools for interacting with Maven builds, analyzing POMs, and managing dependencies.
"""

import asyncio
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from java_upgrade_workflow.state.upgrade_state import BuildResult, DependencyInfo, ErrorInfo


class MavenTool:
    """Maven tool wrapper for build operations."""

    def __init__(
        self,
        project_path: str,
        maven_home: Optional[str] = None,
        settings_file: Optional[str] = None,
    ):
        self.project_path = Path(project_path)
        self.maven_home = maven_home
        self.settings_file = settings_file
        self._mvn_cmd = self._get_maven_command()

    def _get_maven_command(self) -> list[str]:
        """Get the Maven command."""
        if self.maven_home:
            mvn = str(Path(self.maven_home) / "bin" / "mvn")
        else:
            mvn = "mvn"

        cmd = [mvn]
        if self.settings_file:
            cmd.extend(["-s", self.settings_file])
        return cmd

    async def run_command(
        self,
        goals: list[str],
        profiles: Optional[list[str]] = None,
        properties: Optional[dict[str, str]] = None,
        skip_tests: bool = False,
        timeout: int = 600,
    ) -> BuildResult:
        """Run a Maven command."""
        cmd = self._mvn_cmd.copy()
        cmd.extend(goals)

        if profiles:
            cmd.extend(["-P", ",".join(profiles)])

        if properties:
            for key, value in properties.items():
                cmd.append(f"-D{key}={value}")

        if skip_tests:
            cmd.append("-DskipTests")

        cmd.append("-B")  # Batch mode
        cmd.append("--fail-at-end")

        import time
        start_time = time.time()

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
            output = stdout.decode("utf-8", errors="replace")
            duration = time.time() - start_time

            success = process.returncode == 0
            errors = self._parse_errors(output) if not success else []

            return BuildResult(
                success=success,
                phase=goals[-1] if goals else "unknown",
                duration_seconds=duration,
                output=output,
                errors=errors,
                warnings=self._parse_warnings(output),
            )

        except asyncio.TimeoutError:
            return BuildResult(
                success=False,
                phase=goals[-1] if goals else "unknown",
                duration_seconds=timeout,
                output="Build timed out",
                errors=[ErrorInfo(error_type="timeout", message=f"Build timed out after {timeout}s")],
            )
        except Exception as e:
            return BuildResult(
                success=False,
                phase=goals[-1] if goals else "unknown",
                duration_seconds=time.time() - start_time,
                output=str(e),
                errors=[ErrorInfo(error_type="execution", message=str(e))],
            )

    def _parse_errors(self, output: str) -> list[ErrorInfo]:
        """Parse compilation errors from Maven output."""
        errors = []

        # Pattern for compilation errors
        compile_pattern = re.compile(
            r"\[ERROR\]\s+([^:]+):(\[(\d+),(\d+)\])?\s+error:\s+(.+)"
        )

        # Pattern for general errors
        general_pattern = re.compile(r"\[ERROR\]\s+(.+)")

        for match in compile_pattern.finditer(output):
            file_path = match.group(1)
            line = int(match.group(3)) if match.group(3) else None
            column = int(match.group(4)) if match.group(4) else None
            message = match.group(5)

            errors.append(ErrorInfo(
                error_type="compilation",
                message=message,
                file_path=file_path,
                line_number=line,
                column=column,
            ))

        # If no specific errors found, look for general error messages
        if not errors:
            for match in general_pattern.finditer(output):
                message = match.group(1)
                if not message.startswith("->") and "BUILD FAILURE" not in message:
                    errors.append(ErrorInfo(
                        error_type="general",
                        message=message,
                    ))

        return errors

    def _parse_warnings(self, output: str) -> list[str]:
        """Parse warnings from Maven output."""
        warnings = []
        warning_pattern = re.compile(r"\[WARNING\]\s+(.+)")

        for match in warning_pattern.finditer(output):
            warnings.append(match.group(1))

        return warnings

    def run_sync(
        self,
        goals: list[str],
        skip_tests: bool = False,
        timeout: int = 600,
    ) -> BuildResult:
        """Synchronous version of run_command."""
        return asyncio.get_event_loop().run_until_complete(
            self.run_command(goals, skip_tests=skip_tests, timeout=timeout)
        )


class PomAnalyzer:
    """Analyzer for Maven POM files."""

    NAMESPACES = {"maven": "http://maven.apache.org/POM/4.0.0"}

    def __init__(self, pom_path: str | Path):
        self.pom_path = Path(pom_path)
        self.tree = ET.parse(self.pom_path)
        self.root = self.tree.getroot()
        self._detect_namespace()

    def _detect_namespace(self) -> None:
        """Detect the POM namespace."""
        if self.root.tag.startswith("{"):
            self.ns = {"maven": self.root.tag.split("}")[0].strip("{")}
        else:
            self.ns = {}

    def _find(self, xpath: str) -> Optional[ET.Element]:
        """Find element with namespace handling."""
        if self.ns:
            return self.root.find(xpath, self.ns)
        return self.root.find(xpath.replace("maven:", ""))

    def _findall(self, xpath: str) -> list[ET.Element]:
        """Find all elements with namespace handling."""
        if self.ns:
            return self.root.findall(xpath, self.ns)
        return self.root.findall(xpath.replace("maven:", ""))

    def get_project_info(self) -> dict[str, Any]:
        """Extract project information from POM."""
        info = {}

        group_id = self._find(".//maven:groupId")
        if group_id is not None:
            info["group_id"] = group_id.text

        artifact_id = self._find(".//maven:artifactId")
        if artifact_id is not None:
            info["artifact_id"] = artifact_id.text

        version = self._find(".//maven:version")
        if version is not None:
            info["version"] = version.text

        packaging = self._find(".//maven:packaging")
        info["packaging"] = packaging.text if packaging is not None else "jar"

        return info

    def get_java_version(self) -> Optional[str]:
        """Get the configured Java version."""
        # Check properties
        props = self._find(".//maven:properties")
        if props is not None:
            for prop in ["java.version", "maven.compiler.source", "maven.compiler.target"]:
                elem = props.find(f"maven:{prop}" if self.ns else prop, self.ns) if self.ns else props.find(prop)
                if elem is not None:
                    return elem.text

        # Check compiler plugin
        plugins = self._findall(".//maven:plugin")
        for plugin in plugins:
            artifact = plugin.find("maven:artifactId" if self.ns else "artifactId", self.ns) if self.ns else plugin.find("artifactId")
            if artifact is not None and artifact.text == "maven-compiler-plugin":
                config = plugin.find("maven:configuration" if self.ns else "configuration", self.ns) if self.ns else plugin.find("configuration")
                if config is not None:
                    source = config.find("maven:source" if self.ns else "source", self.ns) if self.ns else config.find("source")
                    if source is not None:
                        return source.text

        return None

    def get_spring_boot_version(self) -> Optional[str]:
        """Get the Spring Boot version."""
        # Check parent
        parent = self._find(".//maven:parent")
        if parent is not None:
            artifact = parent.find("maven:artifactId" if self.ns else "artifactId", self.ns) if self.ns else parent.find("artifactId")
            if artifact is not None and "spring-boot" in artifact.text:
                version = parent.find("maven:version" if self.ns else "version", self.ns) if self.ns else parent.find("version")
                if version is not None:
                    return version.text

        # Check dependency management
        deps = self._findall(".//maven:dependencyManagement//maven:dependency")
        for dep in deps:
            artifact = dep.find("maven:artifactId" if self.ns else "artifactId", self.ns) if self.ns else dep.find("artifactId")
            if artifact is not None and "spring-boot-dependencies" in artifact.text:
                version = dep.find("maven:version" if self.ns else "version", self.ns) if self.ns else dep.find("version")
                if version is not None:
                    return version.text

        return None

    def get_dependencies(self) -> list[DependencyInfo]:
        """Get all project dependencies."""
        dependencies = []

        deps = self._findall(".//maven:dependencies/maven:dependency")
        for dep in deps:
            group = dep.find("maven:groupId" if self.ns else "groupId", self.ns) if self.ns else dep.find("groupId")
            artifact = dep.find("maven:artifactId" if self.ns else "artifactId", self.ns) if self.ns else dep.find("artifactId")
            version = dep.find("maven:version" if self.ns else "version", self.ns) if self.ns else dep.find("version")
            scope = dep.find("maven:scope" if self.ns else "scope", self.ns) if self.ns else dep.find("scope")

            if group is not None and artifact is not None:
                dependencies.append(DependencyInfo(
                    group_id=group.text,
                    artifact_id=artifact.text,
                    current_version=version.text if version is not None else "unknown",
                    scope=scope.text if scope is not None else "compile",
                    is_spring="spring" in group.text.lower() or "spring" in artifact.text.lower(),
                ))

        return dependencies


# LangChain tool definitions

@tool
def run_maven_build(
    project_path: str,
    goals: str = "clean compile",
    skip_tests: bool = False,
) -> dict[str, Any]:
    """
    Run a Maven build on the Java project.

    Args:
        project_path: Path to the Maven project
        goals: Maven goals to execute (space-separated)
        skip_tests: Whether to skip tests

    Returns:
        Build result with success status, output, and any errors
    """
    maven = MavenTool(project_path)
    goal_list = goals.split()
    result = maven.run_sync(goal_list, skip_tests=skip_tests)

    return {
        "success": result.success,
        "phase": result.phase,
        "duration": result.duration_seconds,
        "errors": [e.model_dump() for e in result.errors],
        "warnings": result.warnings[:10],  # Limit warnings
        "output_preview": result.output[-2000:] if len(result.output) > 2000 else result.output,
    }


@tool
def run_maven_test(project_path: str, test_class: Optional[str] = None) -> dict[str, Any]:
    """
    Run Maven tests on the Java project.

    Args:
        project_path: Path to the Maven project
        test_class: Specific test class to run (optional)

    Returns:
        Test result with pass/fail counts
    """
    maven = MavenTool(project_path)
    goals = ["test"]
    properties = {}

    if test_class:
        properties["test"] = test_class

    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(
        maven.run_command(goals, properties=properties)
    )
    loop.close()

    # Parse test results from output
    test_count = re.search(r"Tests run: (\d+)", result.output)
    failures = re.search(r"Failures: (\d+)", result.output)
    errors = re.search(r"Errors: (\d+)", result.output)
    skipped = re.search(r"Skipped: (\d+)", result.output)

    return {
        "success": result.success,
        "total_tests": int(test_count.group(1)) if test_count else 0,
        "failures": int(failures.group(1)) if failures else 0,
        "errors": int(errors.group(1)) if errors else 0,
        "skipped": int(skipped.group(1)) if skipped else 0,
        "duration": result.duration_seconds,
        "output_preview": result.output[-2000:] if len(result.output) > 2000 else result.output,
    }


@tool
def analyze_pom(pom_path: str) -> dict[str, Any]:
    """
    Analyze a Maven POM file.

    Args:
        pom_path: Path to pom.xml file

    Returns:
        Project info including Java version, dependencies, etc.
    """
    try:
        analyzer = PomAnalyzer(pom_path)

        return {
            "success": True,
            "project_info": analyzer.get_project_info(),
            "java_version": analyzer.get_java_version(),
            "spring_boot_version": analyzer.get_spring_boot_version(),
            "dependencies": [d.model_dump() for d in analyzer.get_dependencies()],
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@tool
def update_dependency(
    pom_path: str,
    group_id: str,
    artifact_id: str,
    new_version: str,
) -> dict[str, Any]:
    """
    Update a dependency version in pom.xml.

    Args:
        pom_path: Path to pom.xml
        group_id: Dependency group ID
        artifact_id: Dependency artifact ID
        new_version: New version to set

    Returns:
        Result of the update operation
    """
    try:
        # Read the file
        with open(pom_path, "r") as f:
            content = f.read()

        # Simple regex-based update (preserves formatting better than XML parsing)
        # Pattern to find the dependency block
        pattern = re.compile(
            rf"(<dependency>\s*"
            rf"<groupId>{re.escape(group_id)}</groupId>\s*"
            rf"<artifactId>{re.escape(artifact_id)}</artifactId>\s*"
            rf"<version>)[^<]+(</version>)",
            re.DOTALL
        )

        new_content, count = pattern.subn(rf"\g<1>{new_version}\g<2>", content)

        if count > 0:
            with open(pom_path, "w") as f:
                f.write(new_content)

            return {
                "success": True,
                "message": f"Updated {group_id}:{artifact_id} to version {new_version}",
                "changes_made": count,
            }
        else:
            return {
                "success": False,
                "message": f"Dependency {group_id}:{artifact_id} not found in {pom_path}",
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }
