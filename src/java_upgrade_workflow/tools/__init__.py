"""Tools for Java Upgrade Workflow agents."""

from java_upgrade_workflow.tools.maven_tools import (
    MavenTool,
    PomAnalyzer,
    MultiModulePomAnalyzer,
    ModuleInfo,
    MultiModuleProject,
    run_maven_build,
    run_maven_test,
    analyze_pom,
    update_dependency,
    analyze_multi_module_project,
    run_multi_module_build,
    update_parent_pom_version,
    update_all_module_poms,
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
    # Maven tools
    "MavenTool",
    "PomAnalyzer",
    "MultiModulePomAnalyzer",
    "ModuleInfo",
    "MultiModuleProject",
    "run_maven_build",
    "run_maven_test",
    "analyze_pom",
    "update_dependency",
    "analyze_multi_module_project",
    "run_multi_module_build",
    "update_parent_pom_version",
    "update_all_module_poms",
    # Code tools
    "CodeAnalysisTool",
    "read_java_file",
    "write_java_file",
    "find_java_files",
    "search_code_pattern",
    "apply_code_fix",
    # Git tools
    "GitTool",
    "create_branch",
    "commit_changes",
    "get_diff",
]
