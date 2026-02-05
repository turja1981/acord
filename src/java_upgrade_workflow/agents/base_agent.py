"""
Base Agent

Abstract base class for all upgrade agents.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

import litellm
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from java_upgrade_workflow.config.litellm_config import LiteLLMConfig
from java_upgrade_workflow.state.upgrade_state import UpgradeState


class AgentConfig(BaseModel):
    """Configuration for an agent."""

    name: str
    description: str
    system_prompt: str
    max_iterations: int = 5
    temperature: float = 0.1


class BaseUpgradeAgent(ABC):
    """
    Base class for all upgrade agents.

    Provides common functionality for:
    - LLM interaction through LiteLLM
    - State management
    - Tool execution
    - Logging and metrics
    """

    def __init__(
        self,
        config: AgentConfig,
        llm_config: LiteLLMConfig,
        tools: Optional[list[Any]] = None,
    ):
        self.config = config
        self.llm_config = llm_config
        self.tools = tools or []
        self._conversation_history: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        """Get agent name."""
        return self.config.name

    def _get_llm_kwargs(self) -> dict[str, Any]:
        """Get LiteLLM kwargs for this agent."""
        return self.llm_config.get_completion_kwargs(self.name)

    def _format_tools(self) -> list[dict[str, Any]]:
        """Format tools for LiteLLM."""
        if not self.tools:
            return []

        formatted = []
        for tool in self.tools:
            if hasattr(tool, "name") and hasattr(tool, "description"):
                formatted.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.args_schema.model_json_schema() if hasattr(tool, "args_schema") else {},
                    },
                })
        return formatted

    async def _call_llm(
        self,
        messages: list[dict[str, str]],
        use_tools: bool = True,
    ) -> dict[str, Any]:
        """Make an LLM call through LiteLLM."""
        kwargs = self._get_llm_kwargs()

        if use_tools and self.tools:
            kwargs["tools"] = self._format_tools()

        try:
            response = await litellm.acompletion(
                messages=messages,
                **kwargs,
            )

            return {
                "success": True,
                "content": response.choices[0].message.content,
                "tool_calls": getattr(response.choices[0].message, "tool_calls", None),
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def _call_llm_sync(
        self,
        messages: list[dict[str, str]],
        use_tools: bool = True,
    ) -> dict[str, Any]:
        """Synchronous LLM call."""
        kwargs = self._get_llm_kwargs()

        if use_tools and self.tools:
            kwargs["tools"] = self._format_tools()

        try:
            response = litellm.completion(
                messages=messages,
                **kwargs,
            )

            return {
                "success": True,
                "content": response.choices[0].message.content,
                "tool_calls": getattr(response.choices[0].message, "tool_calls", None),
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def _build_messages(
        self,
        state: UpgradeState,
        user_message: str,
    ) -> list[dict[str, str]]:
        """Build message list for LLM."""
        messages = [
            {"role": "system", "content": self.config.system_prompt},
        ]

        # Add context from state
        context = self._build_context(state)
        if context:
            messages.append({"role": "system", "content": f"Current context:\n{context}"})

        # Add conversation history
        messages.extend(self._conversation_history)

        # Add user message
        messages.append({"role": "user", "content": user_message})

        return messages

    def _build_context(self, state: UpgradeState) -> str:
        """Build context string from state."""
        context_parts = []

        if state.project_info:
            context_parts.append(f"Project: {state.project_info.artifact_id}")
            context_parts.append(f"Current Java version: {state.project_info.current_java_version}")
            context_parts.append(f"Target Java version: {state.upgrade_config.target_java_version}")

            if state.project_info.current_spring_boot_version:
                context_parts.append(
                    f"Current Spring Boot: {state.project_info.current_spring_boot_version}"
                )
                context_parts.append(
                    f"Target Spring Boot: {state.upgrade_config.target_spring_boot_version}"
                )

        if state.current_errors:
            context_parts.append(f"Current errors: {len(state.current_errors)}")

        if state.build_successful:
            context_parts.append("Build status: SUCCESS")
        elif state.build_results:
            context_parts.append("Build status: FAILED")

        return "\n".join(context_parts)

    def _execute_tool(self, tool_name: str, tool_args: dict[str, Any]) -> Any:
        """Execute a tool by name."""
        for tool in self.tools:
            if hasattr(tool, "name") and tool.name == tool_name:
                return tool.invoke(tool_args)
        raise ValueError(f"Tool not found: {tool_name}")

    @abstractmethod
    def run(self, state: UpgradeState) -> UpgradeState:
        """
        Execute the agent's main logic.

        Args:
            state: Current upgrade state

        Returns:
            Updated upgrade state
        """
        pass

    def reset(self) -> None:
        """Reset agent conversation history."""
        self._conversation_history = []
