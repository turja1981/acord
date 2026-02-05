"""
Agent Tracking System

Provides consistent tracking comments and markers for all automated changes
made by agents in the Java Upgrade Workflow.
"""

import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class FileType(str, Enum):
    """Supported file types for comment tracking."""
    JAVA = "java"
    XML = "xml"
    YAML = "yaml"
    PROPERTIES = "properties"
    KOTLIN = "kotlin"
    GROOVY = "groovy"
    MARKDOWN = "markdown"
    UNKNOWN = "unknown"


class AgentTrackingInfo(BaseModel):
    """Information for agent tracking."""
    agent_name: str
    agent_version: str = "1.0.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    change_type: str
    description: str
    file_path: str
    module_name: Optional[str] = None
    parent_module: Optional[str] = None
    ticket_id: Optional[str] = None
    correlation_id: Optional[str] = None


# Comment templates for different file types
JAVA_COMMENT_TEMPLATE = """
/*
 * ============================================================================
 * JAVA UPGRADE WORKFLOW - AUTOMATED MODIFICATION
 * ============================================================================
 * Agent: {agent_name} v{agent_version}
 * Timestamp: {timestamp}
 * Change Type: {change_type}
 * Description: {description}
 * Module: {module_name}
 * Correlation ID: {correlation_id}
 * ============================================================================
 * DO NOT REMOVE THIS COMMENT - Used for change tracking and rollback
 * ============================================================================
 */
"""

XML_COMMENT_TEMPLATE = """
<!--
  ============================================================================
  JAVA UPGRADE WORKFLOW - AUTOMATED MODIFICATION
  ============================================================================
  Agent: {agent_name} v{agent_version}
  Timestamp: {timestamp}
  Change Type: {change_type}
  Description: {description}
  Module: {module_name}
  Correlation ID: {correlation_id}
  ============================================================================
  DO NOT REMOVE THIS COMMENT - Used for change tracking and rollback
  ============================================================================
-->
"""

YAML_COMMENT_TEMPLATE = """
# ==============================================================================
# JAVA UPGRADE WORKFLOW - AUTOMATED MODIFICATION
# ==============================================================================
# Agent: {agent_name} v{agent_version}
# Timestamp: {timestamp}
# Change Type: {change_type}
# Description: {description}
# Module: {module_name}
# Correlation ID: {correlation_id}
# ==============================================================================
# DO NOT REMOVE THIS COMMENT - Used for change tracking and rollback
# ==============================================================================
"""

PROPERTIES_COMMENT_TEMPLATE = """
# ==============================================================================
# JAVA UPGRADE WORKFLOW - AUTOMATED MODIFICATION
# ==============================================================================
# Agent: {agent_name} v{agent_version}
# Timestamp: {timestamp}
# Change Type: {change_type}
# Description: {description}
# Module: {module_name}
# Correlation ID: {correlation_id}
# ==============================================================================
"""

# Inline comment templates for specific changes
JAVA_INLINE_COMMENT = "// [UPGRADE:{agent_name}] {description}"
XML_INLINE_COMMENT = "<!-- [UPGRADE:{agent_name}] {description} -->"
YAML_INLINE_COMMENT = "# [UPGRADE:{agent_name}] {description}"


class AgentTracker:
    """
    Manages agent tracking comments for all file modifications.

    This class ensures that all automated changes are properly documented
    with tracking comments that can be used for:
    - Change auditing
    - Rollback identification
    - Multi-agent coordination
    - Debugging and troubleshooting
    """

    # Unique workflow ID for correlating changes
    _workflow_id: Optional[str] = None

    def __init__(self, workflow_id: Optional[str] = None):
        """Initialize the agent tracker."""
        self._workflow_id = workflow_id or datetime.utcnow().strftime("%Y%m%d%H%M%S")
        self._change_counter = 0

    def get_correlation_id(self) -> str:
        """Generate a unique correlation ID for a change."""
        self._change_counter += 1
        return f"{self._workflow_id}-{self._change_counter:04d}"

    @staticmethod
    def detect_file_type(file_path: str) -> FileType:
        """Detect file type from extension."""
        path = Path(file_path)
        ext = path.suffix.lower()

        type_map = {
            '.java': FileType.JAVA,
            '.xml': FileType.XML,
            '.pom': FileType.XML,
            '.yaml': FileType.YAML,
            '.yml': FileType.YAML,
            '.properties': FileType.PROPERTIES,
            '.kt': FileType.KOTLIN,
            '.kts': FileType.KOTLIN,
            '.groovy': FileType.GROOVY,
            '.gradle': FileType.GROOVY,
            '.md': FileType.MARKDOWN,
        }

        return type_map.get(ext, FileType.UNKNOWN)

    def generate_header_comment(self, info: AgentTrackingInfo) -> str:
        """Generate a header comment for a file."""
        file_type = self.detect_file_type(info.file_path)
        correlation_id = info.correlation_id or self.get_correlation_id()

        params = {
            'agent_name': info.agent_name,
            'agent_version': info.agent_version,
            'timestamp': info.timestamp.isoformat(),
            'change_type': info.change_type,
            'description': info.description,
            'module_name': info.module_name or 'root',
            'correlation_id': correlation_id,
        }

        templates = {
            FileType.JAVA: JAVA_COMMENT_TEMPLATE,
            FileType.KOTLIN: JAVA_COMMENT_TEMPLATE,
            FileType.XML: XML_COMMENT_TEMPLATE,
            FileType.YAML: YAML_COMMENT_TEMPLATE,
            FileType.PROPERTIES: PROPERTIES_COMMENT_TEMPLATE,
            FileType.GROOVY: JAVA_COMMENT_TEMPLATE,
        }

        template = templates.get(file_type, JAVA_COMMENT_TEMPLATE)
        return template.format(**params)

    def generate_inline_comment(
        self,
        agent_name: str,
        description: str,
        file_path: str,
    ) -> str:
        """Generate an inline comment for a specific change."""
        file_type = self.detect_file_type(file_path)

        params = {
            'agent_name': agent_name,
            'description': description,
        }

        templates = {
            FileType.JAVA: JAVA_INLINE_COMMENT,
            FileType.KOTLIN: JAVA_INLINE_COMMENT,
            FileType.XML: XML_INLINE_COMMENT,
            FileType.YAML: YAML_INLINE_COMMENT,
            FileType.PROPERTIES: YAML_INLINE_COMMENT,
            FileType.GROOVY: JAVA_INLINE_COMMENT,
        }

        template = templates.get(file_type, JAVA_INLINE_COMMENT)
        return template.format(**params)

    def add_tracking_comment_to_file(
        self,
        file_path: str,
        info: AgentTrackingInfo,
        position: str = "header",  # "header" or "footer"
    ) -> str:
        """Add tracking comment to file content and return modified content."""
        path = Path(file_path)
        if not path.exists():
            return ""

        content = path.read_text(encoding='utf-8')
        comment = self.generate_header_comment(info)

        file_type = self.detect_file_type(file_path)

        if position == "header":
            # For XML files, add after XML declaration if present
            if file_type == FileType.XML:
                if content.startswith('<?xml'):
                    xml_decl_end = content.find('?>') + 2
                    content = content[:xml_decl_end] + '\n' + comment + content[xml_decl_end:]
                else:
                    content = comment + content
            # For Java files, add after package declaration if present
            elif file_type == FileType.JAVA:
                package_match = re.search(r'^package\s+[\w.]+;\s*\n', content, re.MULTILINE)
                if package_match:
                    insert_pos = package_match.end()
                    content = content[:insert_pos] + comment + content[insert_pos:]
                else:
                    content = comment + content
            else:
                content = comment + content
        else:  # footer
            content = content + '\n' + comment

        return content

    def add_inline_tracking(
        self,
        content: str,
        line_number: int,
        agent_name: str,
        description: str,
        file_path: str,
    ) -> str:
        """Add inline tracking comment at a specific line."""
        lines = content.splitlines(keepends=True)

        if 0 < line_number <= len(lines):
            comment = self.generate_inline_comment(agent_name, description, file_path)
            line = lines[line_number - 1].rstrip('\n\r')
            lines[line_number - 1] = f"{line}  {comment}\n"

        return ''.join(lines)

    def extract_tracking_info(self, file_path: str) -> list[AgentTrackingInfo]:
        """Extract tracking information from a file's comments."""
        path = Path(file_path)
        if not path.exists():
            return []

        content = path.read_text(encoding='utf-8')
        tracking_info = []

        # Pattern to find tracking comments
        patterns = [
            # Java/Kotlin style
            r'/\*[\s\S]*?Agent:\s*(\w+)\s*v([\d.]+)[\s\S]*?Timestamp:\s*([\d\-T:.]+)[\s\S]*?Change Type:\s*(\w+)[\s\S]*?Description:\s*(.+?)[\s\S]*?Correlation ID:\s*([\w\-]+)[\s\S]*?\*/',
            # XML style
            r'<!--[\s\S]*?Agent:\s*(\w+)\s*v([\d.]+)[\s\S]*?Timestamp:\s*([\d\-T:.]+)[\s\S]*?Change Type:\s*(\w+)[\s\S]*?Description:\s*(.+?)[\s\S]*?Correlation ID:\s*([\w\-]+)[\s\S]*?-->',
            # YAML/Properties style
            r'#[\s\S]*?Agent:\s*(\w+)\s*v([\d.]+)[\s\S]*?Timestamp:\s*([\d\-T:.]+)[\s\S]*?Change Type:\s*(\w+)[\s\S]*?Description:\s*(.+?)[\s\S]*?Correlation ID:\s*([\w\-]+)',
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, content)
            for match in matches:
                try:
                    tracking_info.append(AgentTrackingInfo(
                        agent_name=match.group(1),
                        agent_version=match.group(2),
                        timestamp=datetime.fromisoformat(match.group(3)),
                        change_type=match.group(4),
                        description=match.group(5).strip(),
                        file_path=file_path,
                        correlation_id=match.group(6),
                    ))
                except Exception:
                    continue

        return tracking_info

    def remove_tracking_comments(self, content: str, file_path: str) -> str:
        """Remove all tracking comments from content (for clean comparison)."""
        file_type = self.detect_file_type(file_path)

        # Remove header comments
        if file_type in (FileType.JAVA, FileType.KOTLIN, FileType.GROOVY):
            content = re.sub(
                r'/\*[\s\S]*?JAVA UPGRADE WORKFLOW[\s\S]*?\*/',
                '',
                content
            )
        elif file_type == FileType.XML:
            content = re.sub(
                r'<!--[\s\S]*?JAVA UPGRADE WORKFLOW[\s\S]*?-->',
                '',
                content
            )
        elif file_type in (FileType.YAML, FileType.PROPERTIES):
            content = re.sub(
                r'#[^\n]*JAVA UPGRADE WORKFLOW[^\n]*\n(?:#[^\n]*\n)*',
                '',
                content
            )

        # Remove inline comments
        content = re.sub(r'\s*//\s*\[UPGRADE:[^\]]+\][^\n]*', '', content)
        content = re.sub(r'\s*<!--\s*\[UPGRADE:[^\]]+\][^>]*-->', '', content)
        content = re.sub(r'\s*#\s*\[UPGRADE:[^\]]+\][^\n]*', '', content)

        return content


def create_tracking_comment(
    agent_name: str,
    change_type: str,
    description: str,
    file_path: str,
    module_name: Optional[str] = None,
) -> str:
    """Convenience function to create a tracking comment."""
    tracker = AgentTracker()
    info = AgentTrackingInfo(
        agent_name=agent_name,
        change_type=change_type,
        description=description,
        file_path=file_path,
        module_name=module_name,
    )
    return tracker.generate_header_comment(info)
