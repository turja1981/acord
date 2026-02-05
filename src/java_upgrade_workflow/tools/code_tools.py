"""
Code Analysis and Manipulation Tools

Tools for analyzing, searching, and modifying Java source code.
"""

import os
import re
from pathlib import Path
from typing import Any, Optional

from langchain_core.tools import tool


class CodeAnalysisTool:
    """Tool for analyzing Java code."""

    # Common patterns for Java code analysis
    DEPRECATED_PATTERNS = {
        "javax_to_jakarta": {
            "pattern": r"import\s+javax\.(persistence|servlet|validation|annotation|ws|xml|inject)",
            "replacement": r"import jakarta.\1",
            "description": "javax.* packages migrated to jakarta.* in Jakarta EE 9+",
        },
        "spring_security_websecurityconfigureradapter": {
            "pattern": r"extends\s+WebSecurityConfigurerAdapter",
            "replacement": None,  # Requires manual migration
            "description": "WebSecurityConfigurerAdapter deprecated in Spring Security 5.7+",
        },
        "spring_data_querydsladapter": {
            "pattern": r"QuerydslPredicateExecutor<(\w+)>",
            "replacement": None,
            "description": "Check QueryDSL compatibility with Spring Boot 3.x",
        },
        "junit4_to_junit5": {
            "pattern": r"import\s+org\.junit\.(Test|Before|After|BeforeClass|AfterClass|Ignore|Assert)",
            "replacement": None,
            "description": "JUnit 4 annotations should migrate to JUnit 5",
        },
        "javax_inject": {
            "pattern": r"import\s+javax\.inject\.(Inject|Named|Singleton)",
            "replacement": r"import jakarta.inject.\1",
            "description": "javax.inject migrated to jakarta.inject",
        },
    }

    SPRING_BOOT_3_PATTERNS = {
        "spring_httpmessageconverter": {
            "pattern": r"import\s+org\.springframework\.http\.converter\.json\.MappingJacksonHttpMessageConverter",
            "description": "MappingJacksonHttpMessageConverter removed, use MappingJackson2HttpMessageConverter",
        },
        "springfox_swagger": {
            "pattern": r"import\s+springfox\.",
            "description": "Springfox not compatible with Spring Boot 3, migrate to springdoc-openapi",
        },
        "spring_actuator_endpoints": {
            "pattern": r"management\.endpoint\.",
            "description": "Check actuator endpoint configuration changes in Spring Boot 3",
        },
    }

    def __init__(self, project_path: str):
        self.project_path = Path(project_path)

    def find_java_files(self, directory: Optional[str] = None) -> list[str]:
        """Find all Java files in the project."""
        search_path = Path(directory) if directory else self.project_path
        return [str(p) for p in search_path.rglob("*.java")]

    def analyze_file(self, file_path: str) -> dict[str, Any]:
        """Analyze a single Java file for upgrade issues."""
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        issues = []

        # Check deprecated patterns
        for name, pattern_info in self.DEPRECATED_PATTERNS.items():
            matches = re.findall(pattern_info["pattern"], content)
            if matches:
                issues.append({
                    "type": name,
                    "description": pattern_info["description"],
                    "matches": list(set(matches))[:5],  # Limit matches
                    "auto_fixable": pattern_info["replacement"] is not None,
                })

        # Check Spring Boot 3 specific patterns
        for name, pattern_info in self.SPRING_BOOT_3_PATTERNS.items():
            if re.search(pattern_info["pattern"], content):
                issues.append({
                    "type": name,
                    "description": pattern_info["description"],
                    "auto_fixable": False,
                })

        # Analyze imports
        imports = re.findall(r"import\s+([\w.]+);", content)
        javax_imports = [i for i in imports if i.startswith("javax.")]
        spring_imports = [i for i in imports if "springframework" in i]

        # Check for class definitions
        classes = re.findall(r"(?:public\s+)?(?:abstract\s+)?class\s+(\w+)", content)
        interfaces = re.findall(r"(?:public\s+)?interface\s+(\w+)", content)

        return {
            "file_path": file_path,
            "issues": issues,
            "imports": {
                "total": len(imports),
                "javax_count": len(javax_imports),
                "spring_count": len(spring_imports),
            },
            "classes": classes,
            "interfaces": interfaces,
            "lines": content.count("\n") + 1,
        }

    def search_pattern(self, pattern: str, file_types: list[str] = None) -> list[dict[str, Any]]:
        """Search for a regex pattern across files."""
        file_types = file_types or ["*.java"]
        results = []

        for file_type in file_types:
            for file_path in self.project_path.rglob(file_type):
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()

                    for match in re.finditer(pattern, content):
                        line_num = content[:match.start()].count("\n") + 1
                        line = content.split("\n")[line_num - 1]
                        results.append({
                            "file": str(file_path),
                            "line_number": line_num,
                            "line_content": line.strip(),
                            "match": match.group(),
                        })
                except Exception:
                    continue

        return results


# LangChain tool definitions

@tool
def read_java_file(file_path: str) -> dict[str, Any]:
    """
    Read a Java source file.

    Args:
        file_path: Path to the Java file

    Returns:
        File content and metadata
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")

        return {
            "success": True,
            "file_path": file_path,
            "content": content,
            "line_count": len(lines),
            "size_bytes": len(content.encode("utf-8")),
        }
    except FileNotFoundError:
        return {
            "success": False,
            "error": f"File not found: {file_path}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@tool
def write_java_file(file_path: str, content: str) -> dict[str, Any]:
    """
    Write content to a Java source file.

    Args:
        file_path: Path to the Java file
        content: New content for the file

    Returns:
        Result of the write operation
    """
    try:
        # Backup original if it exists
        backup_path = None
        if os.path.exists(file_path):
            backup_path = file_path + ".bak"
            with open(file_path, "r") as f:
                original = f.read()
            with open(backup_path, "w") as f:
                f.write(original)

        # Write new content
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return {
            "success": True,
            "file_path": file_path,
            "backup_path": backup_path,
            "lines_written": content.count("\n") + 1,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@tool
def find_java_files(
    project_path: str,
    pattern: str = "**/*.java",
    exclude_tests: bool = False,
) -> dict[str, Any]:
    """
    Find Java files in a project.

    Args:
        project_path: Root path to search
        pattern: Glob pattern for files
        exclude_tests: Whether to exclude test files

    Returns:
        List of matching file paths
    """
    try:
        project = Path(project_path)
        files = list(project.rglob(pattern))

        if exclude_tests:
            files = [f for f in files if "/test/" not in str(f) and "Test.java" not in str(f)]

        return {
            "success": True,
            "files": [str(f) for f in files],
            "count": len(files),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@tool
def search_code_pattern(
    project_path: str,
    pattern: str,
    file_extension: str = "java",
    max_results: int = 50,
) -> dict[str, Any]:
    """
    Search for a regex pattern in code files.

    Args:
        project_path: Root path to search
        pattern: Regex pattern to search for
        file_extension: File extension to search (without dot)
        max_results: Maximum number of results to return

    Returns:
        Matching locations and content
    """
    try:
        analyzer = CodeAnalysisTool(project_path)
        results = analyzer.search_pattern(pattern, [f"*.{file_extension}"])

        return {
            "success": True,
            "pattern": pattern,
            "matches": results[:max_results],
            "total_matches": len(results),
            "truncated": len(results) > max_results,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@tool
def apply_code_fix(
    file_path: str,
    old_pattern: str,
    new_pattern: str,
    is_regex: bool = True,
) -> dict[str, Any]:
    """
    Apply a code fix by replacing patterns in a file.

    Args:
        file_path: Path to the file to modify
        old_pattern: Pattern to find (string or regex)
        new_pattern: Replacement pattern
        is_regex: Whether old_pattern is a regex

    Returns:
        Result of the fix operation
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            original = f.read()

        if is_regex:
            new_content, count = re.subn(old_pattern, new_pattern, original)
        else:
            count = original.count(old_pattern)
            new_content = original.replace(old_pattern, new_pattern)

        if count > 0:
            # Backup
            with open(file_path + ".bak", "w") as f:
                f.write(original)

            # Write new content
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            return {
                "success": True,
                "file_path": file_path,
                "replacements": count,
                "backup_created": True,
            }
        else:
            return {
                "success": True,
                "file_path": file_path,
                "replacements": 0,
                "message": "Pattern not found in file",
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@tool
def analyze_java_file_for_upgrade(file_path: str) -> dict[str, Any]:
    """
    Analyze a Java file for upgrade-related issues.

    Args:
        file_path: Path to the Java file

    Returns:
        Analysis results including deprecated patterns and migration needs
    """
    try:
        project_path = str(Path(file_path).parent.parent.parent)  # Approximate project root
        analyzer = CodeAnalysisTool(project_path)
        return analyzer.analyze_file(file_path)
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }
