"""
Comparison Report Generator

Generates detailed reports showing file changes, content differences,
and agent activity tracking for the Java upgrade workflow.
"""

import difflib
import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class ChangeType(str, Enum):
    """Types of file changes."""
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    UNCHANGED = "unchanged"


class FileChange(BaseModel):
    """Represents a single file change."""

    file_path: str
    change_type: ChangeType
    agent_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Content tracking
    original_content: Optional[str] = None
    new_content: Optional[str] = None

    # Diff information
    diff_lines: list[str] = Field(default_factory=list)
    lines_added: int = 0
    lines_removed: int = 0

    # Agent tracking comment
    tracking_comment: str = ""

    # Module info for multi-module projects
    module_name: Optional[str] = None
    is_parent_pom: bool = False

    # Description
    description: str = ""
    reason: str = ""


class ModuleChange(BaseModel):
    """Changes within a single Maven module."""

    module_name: str
    module_path: str
    is_parent: bool = False

    # POM changes
    pom_changes: list[FileChange] = Field(default_factory=list)

    # Source changes
    source_changes: list[FileChange] = Field(default_factory=list)

    # Test changes
    test_changes: list[FileChange] = Field(default_factory=list)

    # Resource changes
    resource_changes: list[FileChange] = Field(default_factory=list)

    # Summary
    total_files_changed: int = 0
    total_lines_added: int = 0
    total_lines_removed: int = 0


class ComparisonReport(BaseModel):
    """Complete comparison report for an upgrade operation."""

    # Report metadata
    report_id: str = Field(default_factory=lambda: datetime.utcnow().strftime("%Y%m%d_%H%M%S"))
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    # Project info
    project_path: str
    project_name: str = ""
    is_multi_module: bool = False

    # Upgrade targets
    source_java_version: Optional[str] = None
    target_java_version: str = ""
    source_spring_boot_version: Optional[str] = None
    target_spring_boot_version: str = ""

    # Module changes (for multi-module projects)
    modules: list[ModuleChange] = Field(default_factory=list)

    # All file changes (flattened view)
    all_changes: list[FileChange] = Field(default_factory=list)

    # Agent activity tracking
    agent_activities: list[dict[str, Any]] = Field(default_factory=list)

    # Summary statistics
    total_files_changed: int = 0
    total_lines_added: int = 0
    total_lines_removed: int = 0
    total_modules_affected: int = 0

    # Change breakdown by type
    files_created: int = 0
    files_modified: int = 0
    files_deleted: int = 0

    # Change breakdown by agent
    changes_by_agent: dict[str, int] = Field(default_factory=dict)

    # Errors and warnings
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# Agent tracking comment format
AGENT_TRACKING_COMMENT = """
// ============================================================================
// JAVA UPGRADE WORKFLOW - AUTOMATED CHANGE
// ============================================================================
// Agent: {agent_name}
// Timestamp: {timestamp}
// Change Type: {change_type}
// Description: {description}
// ============================================================================
"""

AGENT_TRACKING_COMMENT_XML = """
<!-- ========================================================================== -->
<!-- JAVA UPGRADE WORKFLOW - AUTOMATED CHANGE                                   -->
<!-- ========================================================================== -->
<!-- Agent: {agent_name}                                                        -->
<!-- Timestamp: {timestamp}                                                     -->
<!-- Change Type: {change_type}                                                 -->
<!-- Description: {description}                                                 -->
<!-- ========================================================================== -->
"""

AGENT_TRACKING_COMMENT_YAML = """
# ==============================================================================
# JAVA UPGRADE WORKFLOW - AUTOMATED CHANGE
# ==============================================================================
# Agent: {agent_name}
# Timestamp: {timestamp}
# Change Type: {change_type}
# Description: {description}
# ==============================================================================
"""


class ComparisonReportGenerator:
    """
    Generates comparison reports for Java upgrade workflows.

    Features:
    - Tracks all file changes with before/after content
    - Generates unified diffs for each change
    - Supports multi-module Maven projects
    - Tracks agent activities
    - Adds tracking comments to modified files
    """

    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.report = ComparisonReport(project_path=str(self.project_path))
        self._original_contents: dict[str, str] = {}
        self._file_backups: dict[str, str] = {}

    def set_project_info(
        self,
        project_name: str,
        is_multi_module: bool,
        source_java: Optional[str],
        target_java: str,
        source_spring: Optional[str],
        target_spring: str,
    ) -> None:
        """Set project information for the report."""
        self.report.project_name = project_name
        self.report.is_multi_module = is_multi_module
        self.report.source_java_version = source_java
        self.report.target_java_version = target_java
        self.report.source_spring_boot_version = source_spring
        self.report.target_spring_boot_version = target_spring

    def backup_file(self, file_path: str) -> None:
        """Backup original file content before modification."""
        path = Path(file_path)
        if path.exists():
            try:
                self._original_contents[file_path] = path.read_text(encoding='utf-8')
            except Exception:
                self._original_contents[file_path] = ""

    def record_change(
        self,
        file_path: str,
        change_type: ChangeType,
        agent_name: str,
        description: str,
        reason: str = "",
        new_content: Optional[str] = None,
        module_name: Optional[str] = None,
        is_parent_pom: bool = False,
    ) -> FileChange:
        """Record a file change."""
        original = self._original_contents.get(file_path)

        # Read new content if not provided
        if new_content is None and change_type != ChangeType.DELETED:
            path = Path(file_path)
            if path.exists():
                try:
                    new_content = path.read_text(encoding='utf-8')
                except Exception:
                    new_content = ""

        # Generate diff
        diff_lines = []
        lines_added = 0
        lines_removed = 0

        if original and new_content:
            diff = difflib.unified_diff(
                original.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
                lineterm=""
            )
            diff_lines = list(diff)

            for line in diff_lines:
                if line.startswith('+') and not line.startswith('+++'):
                    lines_added += 1
                elif line.startswith('-') and not line.startswith('---'):
                    lines_removed += 1
        elif new_content and change_type == ChangeType.CREATED:
            lines_added = len(new_content.splitlines())
        elif original and change_type == ChangeType.DELETED:
            lines_removed = len(original.splitlines())

        # Generate tracking comment
        tracking_comment = self._generate_tracking_comment(
            file_path, agent_name, change_type, description
        )

        change = FileChange(
            file_path=file_path,
            change_type=change_type,
            agent_name=agent_name,
            original_content=original,
            new_content=new_content,
            diff_lines=diff_lines,
            lines_added=lines_added,
            lines_removed=lines_removed,
            tracking_comment=tracking_comment,
            module_name=module_name,
            is_parent_pom=is_parent_pom,
            description=description,
            reason=reason,
        )

        # Add to report
        self.report.all_changes.append(change)
        self._update_statistics(change)

        # Track agent activity
        self._record_agent_activity(agent_name, change)

        return change

    def _generate_tracking_comment(
        self,
        file_path: str,
        agent_name: str,
        change_type: ChangeType,
        description: str,
    ) -> str:
        """Generate appropriate tracking comment based on file type."""
        timestamp = datetime.utcnow().isoformat()

        params = {
            "agent_name": agent_name,
            "timestamp": timestamp,
            "change_type": change_type.value,
            "description": description,
        }

        if file_path.endswith('.xml') or file_path.endswith('.pom'):
            return AGENT_TRACKING_COMMENT_XML.format(**params)
        elif file_path.endswith('.yaml') or file_path.endswith('.yml'):
            return AGENT_TRACKING_COMMENT_YAML.format(**params)
        elif file_path.endswith('.properties'):
            return AGENT_TRACKING_COMMENT_YAML.format(**params).replace('#', '#')
        else:
            return AGENT_TRACKING_COMMENT.format(**params)

    def _update_statistics(self, change: FileChange) -> None:
        """Update report statistics."""
        self.report.total_files_changed += 1
        self.report.total_lines_added += change.lines_added
        self.report.total_lines_removed += change.lines_removed

        if change.change_type == ChangeType.CREATED:
            self.report.files_created += 1
        elif change.change_type == ChangeType.MODIFIED:
            self.report.files_modified += 1
        elif change.change_type == ChangeType.DELETED:
            self.report.files_deleted += 1

        # Track by agent
        agent = change.agent_name
        self.report.changes_by_agent[agent] = self.report.changes_by_agent.get(agent, 0) + 1

    def _record_agent_activity(self, agent_name: str, change: FileChange) -> None:
        """Record agent activity for tracking."""
        self.report.agent_activities.append({
            "agent": agent_name,
            "action": change.change_type.value,
            "file": change.file_path,
            "description": change.description,
            "timestamp": change.timestamp.isoformat(),
            "lines_added": change.lines_added,
            "lines_removed": change.lines_removed,
        })

    def add_module(self, module: ModuleChange) -> None:
        """Add a module to the report."""
        self.report.modules.append(module)
        self.report.total_modules_affected += 1

    def generate_markdown_report(self) -> str:
        """Generate a markdown-formatted report."""
        lines = [
            "# Java Upgrade Comparison Report",
            "",
            f"**Report ID:** {self.report.report_id}",
            f"**Generated:** {self.report.generated_at.isoformat()}",
            "",
            "---",
            "",
            "## Project Information",
            "",
            f"- **Project:** {self.report.project_name or 'Unknown'}",
            f"- **Path:** `{self.report.project_path}`",
            f"- **Multi-module:** {'Yes' if self.report.is_multi_module else 'No'}",
            "",
            "## Upgrade Summary",
            "",
            f"| Property | Before | After |",
            f"|----------|--------|-------|",
            f"| Java Version | {self.report.source_java_version or 'N/A'} | {self.report.target_java_version} |",
            f"| Spring Boot | {self.report.source_spring_boot_version or 'N/A'} | {self.report.target_spring_boot_version} |",
            "",
            "---",
            "",
            "## Change Statistics",
            "",
            f"| Metric | Count |",
            f"|--------|-------|",
            f"| Total Files Changed | {self.report.total_files_changed} |",
            f"| Files Created | {self.report.files_created} |",
            f"| Files Modified | {self.report.files_modified} |",
            f"| Files Deleted | {self.report.files_deleted} |",
            f"| Lines Added | +{self.report.total_lines_added} |",
            f"| Lines Removed | -{self.report.total_lines_removed} |",
        ]

        if self.report.is_multi_module:
            lines.extend([
                f"| Modules Affected | {self.report.total_modules_affected} |",
            ])

        # Changes by agent
        lines.extend([
            "",
            "---",
            "",
            "## Changes by Agent",
            "",
            "| Agent | Files Changed |",
            "|-------|---------------|",
        ])

        for agent, count in sorted(self.report.changes_by_agent.items()):
            lines.append(f"| {agent} | {count} |")

        # Module breakdown (for multi-module projects)
        if self.report.is_multi_module and self.report.modules:
            lines.extend([
                "",
                "---",
                "",
                "## Module Breakdown",
                "",
            ])

            for module in self.report.modules:
                lines.extend([
                    f"### {module.module_name}" + (" (Parent)" if module.is_parent else ""),
                    "",
                    f"- **Path:** `{module.module_path}`",
                    f"- **Files Changed:** {module.total_files_changed}",
                    f"- **Lines:** +{module.total_lines_added} / -{module.total_lines_removed}",
                    "",
                ])

        # Detailed file changes
        lines.extend([
            "",
            "---",
            "",
            "## Detailed File Changes",
            "",
        ])

        for change in self.report.all_changes:
            icon = {
                ChangeType.CREATED: "🆕",
                ChangeType.MODIFIED: "📝",
                ChangeType.DELETED: "🗑️",
                ChangeType.RENAMED: "📋",
            }.get(change.change_type, "•")

            lines.extend([
                f"### {icon} `{change.file_path}`",
                "",
                f"- **Type:** {change.change_type.value}",
                f"- **Agent:** {change.agent_name}",
                f"- **Description:** {change.description}",
            ])

            if change.module_name:
                lines.append(f"- **Module:** {change.module_name}")

            lines.extend([
                f"- **Lines:** +{change.lines_added} / -{change.lines_removed}",
                "",
            ])

            # Add diff if available
            if change.diff_lines:
                lines.extend([
                    "<details>",
                    "<summary>View Diff</summary>",
                    "",
                    "```diff",
                ])
                lines.extend(change.diff_lines[:100])  # Limit diff size
                if len(change.diff_lines) > 100:
                    lines.append(f"... ({len(change.diff_lines) - 100} more lines)")
                lines.extend([
                    "```",
                    "",
                    "</details>",
                    "",
                ])

        # Agent activity log
        lines.extend([
            "",
            "---",
            "",
            "## Agent Activity Log",
            "",
            "| Timestamp | Agent | Action | File | Description |",
            "|-----------|-------|--------|------|-------------|",
        ])

        for activity in self.report.agent_activities[-50:]:  # Last 50 activities
            lines.append(
                f"| {activity['timestamp'][:19]} | {activity['agent']} | "
                f"{activity['action']} | `{activity['file'][-40:]}` | {activity['description'][:50]} |"
            )

        # Errors and warnings
        if self.report.errors or self.report.warnings:
            lines.extend([
                "",
                "---",
                "",
                "## Issues",
                "",
            ])

            if self.report.errors:
                lines.append("### Errors")
                for error in self.report.errors:
                    lines.append(f"- ❌ {error}")

            if self.report.warnings:
                lines.append("### Warnings")
                for warning in self.report.warnings:
                    lines.append(f"- ⚠️ {warning}")

        lines.extend([
            "",
            "---",
            "",
            "*Report generated by Java Upgrade Workflow*",
        ])

        return "\n".join(lines)

    def generate_json_report(self) -> str:
        """Generate a JSON-formatted report."""
        return self.report.model_dump_json(indent=2)

    def generate_html_report(self) -> str:
        """Generate an HTML-formatted report."""
        md_content = self.generate_markdown_report()

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Java Upgrade Comparison Report - {self.report.report_id}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               max-width: 1200px; margin: 0 auto; padding: 20px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f4f4f4; }}
        pre {{ background-color: #f6f8fa; padding: 16px; overflow-x: auto; }}
        code {{ background-color: #f6f8fa; padding: 2px 6px; border-radius: 3px; }}
        .diff-add {{ color: #22863a; background-color: #f0fff4; }}
        .diff-remove {{ color: #cb2431; background-color: #ffeef0; }}
        details {{ margin: 10px 0; }}
        summary {{ cursor: pointer; font-weight: bold; }}
    </style>
</head>
<body>
    <div id="content">
        {self._markdown_to_html(md_content)}
    </div>
</body>
</html>"""
        return html

    def _markdown_to_html(self, md: str) -> str:
        """Simple markdown to HTML conversion."""
        import re

        # Convert headers
        html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', md, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)

        # Convert bold
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)

        # Convert code
        html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)

        # Convert tables (simple)
        html = re.sub(r'^\|(.+)\|$', r'<tr><td>\1</td></tr>', html, flags=re.MULTILINE)

        # Convert lists
        html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)

        # Convert line breaks
        html = html.replace('\n\n', '</p><p>')
        html = f'<p>{html}</p>'

        return html

    def save_reports(self, output_dir: str) -> dict[str, str]:
        """Save reports in multiple formats."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        timestamp = self.report.report_id

        paths = {}

        # Markdown
        md_path = output_path / f"upgrade_report_{timestamp}.md"
        md_path.write_text(self.generate_markdown_report(), encoding='utf-8')
        paths['markdown'] = str(md_path)

        # JSON
        json_path = output_path / f"upgrade_report_{timestamp}.json"
        json_path.write_text(self.generate_json_report(), encoding='utf-8')
        paths['json'] = str(json_path)

        # HTML
        html_path = output_path / f"upgrade_report_{timestamp}.html"
        html_path.write_text(self.generate_html_report(), encoding='utf-8')
        paths['html'] = str(html_path)

        return paths
