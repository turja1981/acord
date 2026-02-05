"""Tools for Java Upgrade Workflow agents."""

from java_upgrade_workflow.tools.maven_tools import (
    MavenTool,
    run_maven_build,
    run_maven_test,
    analyze_pom,
    update_dependency,
)
from java_upgrade_workflow.tools.code_tools import (
    CodeAnalysisTool,
    read_java_file,
    write_java_file,
    find_java_files,
    search_code_pattern,
    apply_code_fix,
)
from java_upgrade_workflow.tools.git_tools import (
    GitTool,
    create_branch,
    commit_changes,
    get_diff,
)

__all__ = [
    "MavenTool",
    "run_maven_build",
    "run_maven_test",
    "analyze_pom",
    "update_dependency",
    "CodeAnalysisTool",
    "read_java_file",
    "write_java_file",
    "find_java_files",
    "search_code_pattern",
    "apply_code_fix",
    "GitTool",
    "create_branch",
    "commit_changes",
    "get_diff",
]
