"""
Maven Build Tools

Tools for interacting with Maven builds, analyzing POMs, and managing dependencies.
Supports both single-module and multi-module (parent-child) Maven projects.
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


class ModuleInfo(BaseModel):
    """Information about a Maven module."""

    name: str
    path: str
    pom_path: str
    artifact_id: str
    group_id: Optional[str] = None
    version: Optional[str] = None
    packaging: str = "jar"
    parent_artifact_id: Optional[str] = None
    parent_path: Optional[str] = None
    is_parent: bool = False
    child_modules: list[str] = Field(default_factory=list)
    dependencies: list[DependencyInfo] = Field(default_factory=list)
    java_version: Optional[str] = None
    spring_boot_version: Optional[str] = None


class MultiModuleProject(BaseModel):
    """Represents a multi-module Maven project structure."""

    root_path: str
    root_pom_path: str
    is_multi_module: bool = False
    parent_module: Optional[ModuleInfo] = None
    modules: list[ModuleInfo] = Field(default_factory=list)
    module_order: list[str] = Field(default_factory=list)  # Build order
    shared_properties: dict[str, str] = Field(default_factory=dict)
    dependency_management: list[DependencyInfo] = Field(default_factory=list)


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

    def get_modules(self) -> list[str]:
        """Get child modules if this is a parent POM."""
        modules = []
        modules_elem = self._findall(".//maven:modules/maven:module")
        for module in modules_elem:
            if module.text:
                modules.append(module.text)
        return modules

    def get_parent_info(self) -> Optional[dict[str, str]]:
        """Get parent POM information."""
        parent = self._find(".//maven:parent")
        if parent is None:
            return None

        info = {}
        group = parent.find("maven:groupId" if self.ns else "groupId", self.ns) if self.ns else parent.find("groupId")
        artifact = parent.find("maven:artifactId" if self.ns else "artifactId", self.ns) if self.ns else parent.find("artifactId")
        version = parent.find("maven:version" if self.ns else "version", self.ns) if self.ns else parent.find("version")
        relative_path = parent.find("maven:relativePath" if self.ns else "relativePath", self.ns) if self.ns else parent.find("relativePath")

        if group is not None:
            info["group_id"] = group.text
        if artifact is not None:
            info["artifact_id"] = artifact.text
        if version is not None:
            info["version"] = version.text
        if relative_path is not None:
            info["relative_path"] = relative_path.text

        return info if info else None

    def get_properties(self) -> dict[str, str]:
        """Get all properties defined in the POM."""
        properties = {}
        props = self._find(".//maven:properties")
        if props is not None:
            for child in props:
                tag = child.tag
                if self.ns and tag.startswith("{"):
                    tag = tag.split("}")[1]
                if child.text:
                    properties[tag] = child.text
        return properties

    def get_dependency_management(self) -> list[DependencyInfo]:
        """Get dependencies from dependencyManagement section."""
        dependencies = []
        deps = self._findall(".//maven:dependencyManagement//maven:dependency")
        for dep in deps:
            group = dep.find("maven:groupId" if self.ns else "groupId", self.ns) if self.ns else dep.find("groupId")
            artifact = dep.find("maven:artifactId" if self.ns else "artifactId", self.ns) if self.ns else dep.find("artifactId")
            version = dep.find("maven:version" if self.ns else "version", self.ns) if self.ns else dep.find("version")
            scope = dep.find("maven:scope" if self.ns else "scope", self.ns) if self.ns else dep.find("scope")

            if group is not None and artifact is not None:
                dependencies.append(DependencyInfo(
                    group_id=group.text,
                    artifact_id=artifact.text,
                    current_version=version.text if version is not None else "${project.version}",
                    scope=scope.text if scope is not None else "compile",
                    is_spring="spring" in group.text.lower() or "spring" in artifact.text.lower(),
                ))
        return dependencies


class MultiModulePomAnalyzer:
    """
    Analyzer for multi-module Maven projects.

    Handles parent-child POM relationships, dependency inheritance,
    and cross-module dependency resolution.
    """

    def __init__(self, root_path: str):
        """Initialize with project root path."""
        self.root_path = Path(root_path)
        self.root_pom_path = self.root_path / "pom.xml"
        self._modules: dict[str, ModuleInfo] = {}
        self._build_order: list[str] = []

    def analyze(self) -> MultiModuleProject:
        """Analyze the complete project structure."""
        if not self.root_pom_path.exists():
            raise FileNotFoundError(f"Root pom.xml not found at {self.root_pom_path}")

        # Analyze root POM
        root_analyzer = PomAnalyzer(self.root_pom_path)
        root_info = root_analyzer.get_project_info()
        child_modules = root_analyzer.get_modules()
        is_multi_module = len(child_modules) > 0 or root_info.get("packaging") == "pom"

        # Create parent module info
        parent_module = ModuleInfo(
            name=root_info.get("artifact_id", "root"),
            path=str(self.root_path),
            pom_path=str(self.root_pom_path),
            artifact_id=root_info.get("artifact_id", "root"),
            group_id=root_info.get("group_id"),
            version=root_info.get("version"),
            packaging=root_info.get("packaging", "pom"),
            is_parent=True,
            child_modules=child_modules,
            java_version=root_analyzer.get_java_version(),
            spring_boot_version=root_analyzer.get_spring_boot_version(),
        )

        self._modules[parent_module.name] = parent_module

        # Analyze child modules
        modules = [parent_module]
        for module_name in child_modules:
            module_info = self._analyze_module(module_name, parent_module)
            if module_info:
                modules.append(module_info)
                self._modules[module_info.name] = module_info

        # Determine build order
        self._build_order = self._calculate_build_order()

        # Get shared properties and dependency management
        shared_properties = root_analyzer.get_properties()
        dependency_management = root_analyzer.get_dependency_management()

        return MultiModuleProject(
            root_path=str(self.root_path),
            root_pom_path=str(self.root_pom_path),
            is_multi_module=is_multi_module,
            parent_module=parent_module,
            modules=modules,
            module_order=self._build_order,
            shared_properties=shared_properties,
            dependency_management=dependency_management,
        )

    def _analyze_module(
        self,
        module_name: str,
        parent: ModuleInfo,
    ) -> Optional[ModuleInfo]:
        """Analyze a child module."""
        module_path = self.root_path / module_name
        module_pom = module_path / "pom.xml"

        if not module_pom.exists():
            return None

        try:
            analyzer = PomAnalyzer(module_pom)
            info = analyzer.get_project_info()
            parent_info = analyzer.get_parent_info()
            child_modules = analyzer.get_modules()

            module_info = ModuleInfo(
                name=module_name,
                path=str(module_path),
                pom_path=str(module_pom),
                artifact_id=info.get("artifact_id", module_name),
                group_id=info.get("group_id") or parent.group_id,
                version=info.get("version") or parent.version,
                packaging=info.get("packaging", "jar"),
                parent_artifact_id=parent_info.get("artifact_id") if parent_info else None,
                parent_path=str(parent.path),
                is_parent=len(child_modules) > 0,
                child_modules=child_modules,
                dependencies=analyzer.get_dependencies(),
                java_version=analyzer.get_java_version() or parent.java_version,
                spring_boot_version=analyzer.get_spring_boot_version() or parent.spring_boot_version,
            )

            # Recursively analyze nested modules
            for nested_module in child_modules:
                nested_path = f"{module_name}/{nested_module}"
                nested_info = self._analyze_module(nested_path, module_info)
                if nested_info:
                    self._modules[nested_info.name] = nested_info

            return module_info

        except Exception:
            return None

    def _calculate_build_order(self) -> list[str]:
        """Calculate the correct build order based on dependencies."""
        # Simple topological sort based on inter-module dependencies
        order = []
        visited = set()
        temp_visited = set()

        def visit(module_name: str) -> None:
            if module_name in temp_visited:
                return  # Circular dependency, skip
            if module_name in visited:
                return

            temp_visited.add(module_name)

            module = self._modules.get(module_name)
            if module:
                # Check dependencies for other modules
                for dep in module.dependencies:
                    dep_name = dep.artifact_id
                    if dep_name in self._modules:
                        visit(dep_name)

            temp_visited.remove(module_name)
            visited.add(module_name)
            order.append(module_name)

        # Visit all modules
        for module_name in self._modules:
            if module_name not in visited:
                visit(module_name)

        return order

    def get_module(self, name: str) -> Optional[ModuleInfo]:
        """Get module info by name."""
        return self._modules.get(name)

    def get_all_pom_paths(self) -> list[str]:
        """Get paths to all POM files in the project."""
        return [m.pom_path for m in self._modules.values()]

    def get_modules_with_dependency(
        self,
        group_id: str,
        artifact_id: str,
    ) -> list[ModuleInfo]:
        """Find all modules that use a specific dependency."""
        result = []
        for module in self._modules.values():
            for dep in module.dependencies:
                if dep.group_id == group_id and dep.artifact_id == artifact_id:
                    result.append(module)
                    break
        return result


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


@tool
def analyze_multi_module_project(project_path: str) -> dict[str, Any]:
    """
    Analyze a multi-module Maven project structure.

    Args:
        project_path: Path to the root of the Maven project

    Returns:
        Complete project structure including all modules, dependencies,
        and build order for multi-module projects
    """
    try:
        analyzer = MultiModulePomAnalyzer(project_path)
        project = analyzer.analyze()

        return {
            "success": True,
            "is_multi_module": project.is_multi_module,
            "root_path": project.root_path,
            "parent_module": project.parent_module.model_dump() if project.parent_module else None,
            "modules": [m.model_dump() for m in project.modules],
            "module_count": len(project.modules),
            "build_order": project.module_order,
            "shared_properties": project.shared_properties,
            "dependency_management": [d.model_dump() for d in project.dependency_management],
            "all_pom_paths": analyzer.get_all_pom_paths(),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@tool
def run_multi_module_build(
    project_path: str,
    goals: str = "clean compile",
    modules: Optional[list[str]] = None,
    skip_tests: bool = False,
    resume_from: Optional[str] = None,
) -> dict[str, Any]:
    """
    Run a Maven build on a multi-module project.

    Args:
        project_path: Path to the root Maven project
        goals: Maven goals to execute (space-separated)
        modules: Specific modules to build (None for all)
        skip_tests: Whether to skip tests
        resume_from: Module to resume build from (after failure)

    Returns:
        Build results for the multi-module project
    """
    maven = MavenTool(project_path)
    goal_list = goals.split()

    properties = {}
    if modules:
        properties["pl"] = ",".join(modules)
        properties["am"] = "true"  # Also make dependencies

    if resume_from:
        properties["rf"] = resume_from

    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(
        maven.run_command(
            goal_list,
            properties=properties,
            skip_tests=skip_tests,
        )
    )
    loop.close()

    # Parse module-specific results from output
    module_results = _parse_module_build_results(result.output)

    return {
        "success": result.success,
        "phase": result.phase,
        "duration": result.duration_seconds,
        "module_results": module_results,
        "errors": [e.model_dump() for e in result.errors],
        "warnings": result.warnings[:10],
        "output_preview": result.output[-3000:] if len(result.output) > 3000 else result.output,
    }


def _parse_module_build_results(output: str) -> list[dict[str, Any]]:
    """Parse build results for each module from Maven output."""
    module_results = []

    # Pattern to find module build status
    success_pattern = re.compile(
        r"\[INFO\] (\S+)\s+\.+\s+(SUCCESS|FAILURE)\s+\[\s*([\d.]+)\s*s\]"
    )

    for match in success_pattern.finditer(output):
        module_results.append({
            "module": match.group(1),
            "status": match.group(2),
            "duration": float(match.group(3)),
        })

    return module_results


@tool
def update_parent_pom_version(
    pom_path: str,
    new_version: str,
    property_name: Optional[str] = None,
) -> dict[str, Any]:
    """
    Update the parent POM version or a version property in the parent POM.

    Args:
        pom_path: Path to the parent pom.xml
        new_version: New version to set
        property_name: Optional property name to update instead of parent version

    Returns:
        Result of the update operation
    """
    try:
        with open(pom_path, "r") as f:
            content = f.read()

        if property_name:
            # Update a specific property
            pattern = re.compile(
                rf"(<{re.escape(property_name)}>)[^<]+(</\s*{re.escape(property_name)}>)",
                re.DOTALL
            )
        else:
            # Update the project version
            pattern = re.compile(
                r"(<project[^>]*>[\s\S]*?<version>)[^<]+(</version>)",
                re.DOTALL
            )

        new_content, count = pattern.subn(rf"\g<1>{new_version}\g<2>", content, count=1)

        if count > 0:
            with open(pom_path, "w") as f:
                f.write(new_content)

            return {
                "success": True,
                "message": f"Updated {'property ' + property_name if property_name else 'version'} to {new_version}",
                "pom_path": pom_path,
            }
        else:
            return {
                "success": False,
                "message": f"Could not find {'property ' + property_name if property_name else 'version'} in {pom_path}",
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@tool
def update_all_module_poms(
    project_path: str,
    updates: dict[str, str],
) -> dict[str, Any]:
    """
    Update properties or versions across all module POMs in a multi-module project.

    Args:
        project_path: Path to the root Maven project
        updates: Dictionary of property names to new values

    Returns:
        Results of updates across all modules
    """
    try:
        analyzer = MultiModulePomAnalyzer(project_path)
        project = analyzer.analyze()

        results = []
        total_updated = 0

        for pom_path in analyzer.get_all_pom_paths():
            with open(pom_path, "r") as f:
                content = f.read()

            original_content = content
            changes_in_file = 0

            for prop_name, new_value in updates.items():
                # Update property
                pattern = re.compile(
                    rf"(<{re.escape(prop_name)}>)[^<]+(</\s*{re.escape(prop_name)}>)",
                    re.DOTALL
                )
                content, count = pattern.subn(rf"\g<1>{new_value}\g<2>", content)
                changes_in_file += count

            if content != original_content:
                with open(pom_path, "w") as f:
                    f.write(content)
                total_updated += 1
                results.append({
                    "pom_path": pom_path,
                    "changes": changes_in_file,
                })

        return {
            "success": True,
            "total_poms_updated": total_updated,
            "results": results,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }