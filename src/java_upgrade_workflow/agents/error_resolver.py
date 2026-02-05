"""
Error Resolver Agent

Handles automatic resolution of build and test errors.
"""

import re
from typing import Any, Optional

from java_upgrade_workflow.agents.base_agent import AgentConfig, BaseUpgradeAgent
from java_upgrade_workflow.config.litellm_config import LiteLLMConfig
from java_upgrade_workflow.state.upgrade_state import (
    CodeChange,
    ErrorInfo,
    UpgradePhase,
    UpgradeState,
)
from java_upgrade_workflow.tools.code_tools import (
    read_java_file,
    write_java_file,
    apply_code_fix,
    search_code_pattern,
)


ERROR_RESOLVER_PROMPT = """You are a Java Build Error Resolution Expert.

Your role is to analyze and fix build/compilation errors:

Common error types and solutions:

1. Import Errors:
   - "cannot find symbol" for javax.* -> Add jakarta.* import
   - Missing class -> Check dependency or add import

2. API Changes:
   - Method signature changes -> Update method calls
   - Removed methods -> Use replacement API
   - Changed return types -> Update variable types

3. Deprecation/Removal:
   - Spring Security changes -> Migrate to new patterns
   - javax.* removal -> Migrate to jakarta.*
   - Removed configuration options -> Use new alternatives

4. Test Errors:
   - JUnit assertion changes -> Update to JUnit 5 syntax
   - Mock framework changes -> Update Mockito syntax

For each error:
1. Identify the exact cause
2. Determine the minimal fix needed
3. Apply the fix precisely
4. Verify the fix doesn't break other code

Provide specific, tested solutions. Avoid over-engineering fixes."""


# Common error patterns and their fixes
ERROR_FIX_PATTERNS = {
    "cannot_find_javax": {
        "pattern": r"cannot find symbol.*symbol:\s+class\s+(\w+).*location:\s+package\s+javax\.",
        "fix_type": "import_replacement",
        "fix": lambda m: f"Replace javax.* import with jakarta.* for {m.group(1)}",
    },
    "incompatible_types_optional": {
        "pattern": r"incompatible types.*Optional<.*>.*cannot be converted",
        "fix_type": "type_conversion",
        "fix": lambda m: "Add .orElse(null) or .orElseThrow() to Optional chain",
    },
    "method_not_found": {
        "pattern": r"cannot find symbol.*method\s+(\w+)\(",
        "fix_type": "method_update",
        "fix": lambda m: f"Method {m.group(1)} may have been renamed or removed",
    },
    "abstract_method": {
        "pattern": r"class.*must.*implement.*abstract method",
        "fix_type": "implement_method",
        "fix": lambda m: "Implement required abstract method or update class hierarchy",
    },
}


class ErrorResolverAgent(BaseUpgradeAgent):
    """
    Agent responsible for resolving build errors.

    Responsibilities:
    - Analyze compilation errors
    - Apply automated fixes
    - Use LLM for complex error resolution
    - Track resolution attempts
    """

    def __init__(self, llm_config: LiteLLMConfig):
        config = AgentConfig(
            name="error_resolver",
            description="Resolves build and compilation errors",
            system_prompt=ERROR_RESOLVER_PROMPT,
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
        """Execute error resolution process."""
        state.current_agent = self.name
        state.phase = UpgradePhase.ERROR_RESOLUTION
        state.add_agent_message(self.name, f"Resolving {len(state.current_errors)} errors")

        errors_to_resolve = state.get_unresolved_errors()
        max_attempts = state.upgrade_config.error_resolution_attempts

        for error in errors_to_resolve:
            if error.resolution_attempts >= max_attempts:
                state.add_agent_message(
                    self.name,
                    f"Max attempts reached for error: {error.message[:50]}..."
                )
                continue

            error.resolution_attempts += 1

            # Try automated fix first
            fixed = self._try_automated_fix(error, state)

            if not fixed:
                # Use LLM for complex errors
                fixed = self._llm_resolve_error(error, state)

            if fixed:
                state.resolve_error(error)

        remaining = len(state.get_unresolved_errors())
        state.add_agent_message(
            self.name,
            f"Error resolution complete. Resolved {state.total_errors_resolved}, "
            f"remaining: {remaining}"
        )

        if remaining > 0 and all(e.resolution_attempts >= max_attempts for e in state.get_unresolved_errors()):
            state.requires_manual_intervention = True
            state.manual_intervention_reason = f"{remaining} errors could not be automatically resolved"

        return state

    def _try_automated_fix(self, error: ErrorInfo, state: UpgradeState) -> bool:
        """Try to apply an automated fix for the error."""
        if not error.file_path:
            return False

        # Check for javax import errors
        if "javax." in error.message and "cannot find symbol" in error.message:
            return self._fix_javax_import(error, state)

        # Check for method signature changes
        if "cannot find symbol" in error.message and "method" in error.message:
            return self._fix_method_not_found(error, state)

        # Check for type mismatches
        if "incompatible types" in error.message:
            return self._fix_type_mismatch(error, state)

        return False

    def _fix_javax_import(self, error: ErrorInfo, state: UpgradeState) -> bool:
        """Fix javax.* to jakarta.* import errors."""
        if not error.file_path:
            return False

        result = read_java_file.invoke({"file_path": error.file_path})
        if not result.get("success"):
            return False

        content = result.get("content", "")

        # Find and replace javax imports
        javax_pattern = r"import\s+(javax\.(\w+)\.[^;]+);"
        matches = list(re.finditer(javax_pattern, content))

        if not matches:
            return False

        modified = False
        for match in matches:
            full_import = match.group(1)
            package = match.group(2)

            # Only replace relevant javax packages
            if package in ["persistence", "servlet", "validation", "annotation", "inject", "ws"]:
                jakarta_import = full_import.replace("javax.", "jakarta.")
                content = content.replace(f"import {full_import};", f"import {jakarta_import};")
                modified = True

        if modified:
            write_result = write_java_file.invoke({
                "file_path": error.file_path,
                "content": content,
            })

            if write_result.get("success"):
                state.code_changes.append(CodeChange(
                    file_path=error.file_path,
                    change_type="modify",
                    description="Fixed javax to jakarta imports",
                    agent=self.name,
                ))
                return True

        return False

    def _fix_method_not_found(self, error: ErrorInfo, state: UpgradeState) -> bool:
        """Fix method not found errors with common replacements."""
        if not error.file_path:
            return False

        # Common method replacements for Spring Boot 3
        method_replacements = {
            "antMatchers": "requestMatchers",
            "authorizeRequests": "authorizeHttpRequests",
            "access": "hasAuthority",
            "mvcMatchers": "requestMatchers",
            "regexMatchers": "requestMatchers",
        }

        result = read_java_file.invoke({"file_path": error.file_path})
        if not result.get("success"):
            return False

        content = result.get("content", "")
        modified = False

        for old_method, new_method in method_replacements.items():
            if old_method in error.message and old_method in content:
                # Simple replacement - may need context-aware replacement for complex cases
                content = re.sub(
                    rf"\.{old_method}\s*\(",
                    f".{new_method}(",
                    content
                )
                modified = True

        if modified:
            write_result = write_java_file.invoke({
                "file_path": error.file_path,
                "content": content,
            })

            if write_result.get("success"):
                state.code_changes.append(CodeChange(
                    file_path=error.file_path,
                    change_type="modify",
                    description=f"Updated deprecated method calls",
                    agent=self.name,
                ))
                return True

        return False

    def _fix_type_mismatch(self, error: ErrorInfo, state: UpgradeState) -> bool:
        """Fix type mismatch errors."""
        # This typically requires LLM assistance for complex cases
        return False

    def _llm_resolve_error(self, error: ErrorInfo, state: UpgradeState) -> bool:
        """Use LLM to resolve complex errors."""
        if not error.file_path:
            return self._llm_resolve_without_file(error, state)

        result = read_java_file.invoke({"file_path": error.file_path})
        if not result.get("success"):
            return False

        content = result.get("content", "")

        # Extract relevant portion of code around the error
        if error.line_number:
            lines = content.split("\n")
            start = max(0, error.line_number - 10)
            end = min(len(lines), error.line_number + 10)
            context = "\n".join(lines[start:end])
        else:
            context = content[:2000]

        message = f"""Fix this Java compilation error:

Error: {error.message}
File: {error.file_path}
Line: {error.line_number}

Code context:
```java
{context}
```

Provide the corrected code. Only output the fixed portion of code that needs to change.
Include the complete method or block that needs modification."""

        messages = self._build_messages(state, message)
        response = self._call_llm_sync(messages, use_tools=False)

        if response.get("success") and response.get("content"):
            fixed_code = self._extract_code_block(response.get("content", ""))
            if fixed_code:
                return self._apply_llm_fix(error, content, fixed_code, state)

        return False

    def _llm_resolve_without_file(self, error: ErrorInfo, state: UpgradeState) -> bool:
        """Resolve error when file path is not available."""
        message = f"""Analyze this Java build error and provide a solution:

Error: {error.message}
Type: {error.error_type}
Stack trace: {error.stack_trace or 'Not available'}

What is the likely cause and how should it be fixed?"""

        messages = self._build_messages(state, message)
        response = self._call_llm_sync(messages, use_tools=False)

        if response.get("success"):
            error.suggested_fix = response.get("content", "")
            return False  # Can't auto-fix without file

        return False

    def _extract_code_block(self, text: str) -> Optional[str]:
        """Extract code block from LLM response."""
        java_pattern = r"```java\n([\s\S]*?)```"
        match = re.search(java_pattern, text)
        if match:
            return match.group(1).strip()

        code_pattern = r"```\n([\s\S]*?)```"
        match = re.search(code_pattern, text)
        if match:
            return match.group(1).strip()

        return None

    def _apply_llm_fix(
        self,
        error: ErrorInfo,
        original_content: str,
        fixed_code: str,
        state: UpgradeState
    ) -> bool:
        """Apply the LLM-suggested fix to the file."""
        if not error.file_path:
            return False

        # For now, only apply fixes if they look like complete methods/blocks
        if "public " in fixed_code or "private " in fixed_code or "protected " in fixed_code:
            # Try to find and replace the method/block
            # This is a simplified approach - in production, use AST-based replacement

            # Extract method name from fixed code
            method_match = re.search(r"(public|private|protected)\s+[\w<>,\s]+\s+(\w+)\s*\(", fixed_code)
            if method_match:
                method_name = method_match.group(2)

                # Find original method in content
                original_method_pattern = rf"(public|private|protected)\s+[\w<>,\s]+\s+{method_name}\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{{[\s\S]*?\n\s*\}}"
                match = re.search(original_method_pattern, original_content)

                if match:
                    new_content = original_content.replace(match.group(0), fixed_code)

                    write_result = write_java_file.invoke({
                        "file_path": error.file_path,
                        "content": new_content,
                    })

                    if write_result.get("success"):
                        state.code_changes.append(CodeChange(
                            file_path=error.file_path,
                            change_type="modify",
                            description=f"Applied LLM fix for: {error.message[:50]}...",
                            agent=self.name,
                        ))
                        return True

        return False
