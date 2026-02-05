"""
LiteLLM Configuration for Externalized LLM Management

This module provides flexible LLM configuration through LiteLLM, enabling:
- Multi-provider support (OpenAI, Anthropic, Azure, AWS Bedrock, etc.)
- Easy model switching without code changes
- Fallback configurations for resilience
- Cost tracking and rate limiting
"""

import os
from typing import Any, Optional
from pathlib import Path

import yaml
import litellm
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class ModelConfig(BaseModel):
    """Configuration for a single LLM model."""

    model_name: str = Field(description="LiteLLM model identifier (e.g., 'gpt-4', 'claude-3-opus')")
    provider: str = Field(default="openai", description="LLM provider name")
    api_base: Optional[str] = Field(default=None, description="Custom API base URL")
    api_key_env: str = Field(default="OPENAI_API_KEY", description="Environment variable for API key")
    max_tokens: int = Field(default=4096, description="Maximum tokens for completion")
    temperature: float = Field(default=0.1, description="Sampling temperature")
    timeout: int = Field(default=120, description="Request timeout in seconds")
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    fallback_models: list[str] = Field(default_factory=list, description="Fallback model names")

    # Cost tracking
    input_cost_per_1k: float = Field(default=0.0, description="Cost per 1K input tokens")
    output_cost_per_1k: float = Field(default=0.0, description="Cost per 1K output tokens")

    # Rate limiting
    requests_per_minute: Optional[int] = Field(default=None, description="Rate limit RPM")
    tokens_per_minute: Optional[int] = Field(default=None, description="Rate limit TPM")

    model_config = {"extra": "allow"}


class AgentModelMapping(BaseModel):
    """Maps agents to their preferred models."""

    code_analyzer: str = Field(default="gpt-4-turbo", description="Model for code analysis")
    dependency_upgrader: str = Field(default="gpt-4-turbo", description="Model for dependency upgrades")
    code_migrator: str = Field(default="claude-3-opus", description="Model for code migration")
    build_agent: str = Field(default="gpt-4-turbo", description="Model for build operations")
    error_resolver: str = Field(default="claude-3-opus", description="Model for error resolution")
    deployment_agent: str = Field(default="gpt-4-turbo", description="Model for deployment tasks")
    orchestrator: str = Field(default="gpt-4-turbo", description="Model for workflow orchestration")

    model_config = {"extra": "allow"}


class LiteLLMConfig(BaseSettings):
    """
    Main LiteLLM configuration class.

    Configuration can be loaded from:
    1. Environment variables (LITELLM_*)
    2. YAML configuration file
    3. Direct instantiation
    """

    # Global settings
    default_model: str = Field(default="gpt-4-turbo", description="Default model for all agents")
    enable_caching: bool = Field(default=True, description="Enable LiteLLM response caching")
    cache_type: str = Field(default="local", description="Cache type: local, redis, s3")
    enable_logging: bool = Field(default=True, description="Enable request/response logging")
    log_level: str = Field(default="INFO", description="Logging level")

    # Cost and usage tracking
    enable_cost_tracking: bool = Field(default=True, description="Track API costs")
    budget_limit: Optional[float] = Field(default=None, description="Maximum budget in USD")

    # Model configurations
    models: dict[str, ModelConfig] = Field(default_factory=dict, description="Model configurations")

    # Agent model mappings
    agent_models: AgentModelMapping = Field(
        default_factory=AgentModelMapping,
        description="Agent to model mappings"
    )

    # Fallback settings
    enable_fallbacks: bool = Field(default=True, description="Enable automatic fallbacks")
    fallback_strategy: str = Field(default="sequential", description="Fallback strategy")

    model_config = {"env_prefix": "LITELLM_", "extra": "allow"}

    @classmethod
    def from_yaml(cls, config_path: str | Path) -> "LiteLLMConfig":
        """Load configuration from a YAML file."""
        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path) as f:
            config_data = yaml.safe_load(f)

        # Parse model configurations
        if "models" in config_data:
            config_data["models"] = {
                name: ModelConfig(**model_data)
                for name, model_data in config_data["models"].items()
            }

        # Parse agent model mappings
        if "agent_models" in config_data:
            config_data["agent_models"] = AgentModelMapping(**config_data["agent_models"])

        return cls(**config_data)

    def initialize_litellm(self) -> None:
        """Initialize LiteLLM with the current configuration."""
        # Set global LiteLLM settings
        litellm.drop_params = True
        litellm.set_verbose = self.log_level == "DEBUG"

        # Enable caching if configured
        if self.enable_caching:
            if self.cache_type == "local":
                litellm.cache = litellm.Cache()
            # Add redis/s3 cache configuration as needed

        # Set up callbacks for cost tracking
        if self.enable_cost_tracking:
            litellm.success_callback = ["langfuse"] if os.getenv("LANGFUSE_PUBLIC_KEY") else []

        # Configure model-specific settings
        for model_name, model_config in self.models.items():
            api_key = os.getenv(model_config.api_key_env)
            if api_key and model_config.api_base:
                litellm.api_base = model_config.api_base

    def get_model_for_agent(self, agent_name: str) -> str:
        """Get the configured model for a specific agent."""
        agent_model_map = self.agent_models.model_dump()
        return agent_model_map.get(agent_name, self.default_model)

    def get_model_config(self, model_name: str) -> ModelConfig:
        """Get configuration for a specific model."""
        if model_name in self.models:
            return self.models[model_name]
        # Return default configuration
        return ModelConfig(model_name=model_name)

    def get_completion_kwargs(self, agent_name: str) -> dict[str, Any]:
        """Get LiteLLM completion kwargs for an agent."""
        model_name = self.get_model_for_agent(agent_name)
        model_config = self.get_model_config(model_name)

        kwargs: dict[str, Any] = {
            "model": model_config.model_name,
            "max_tokens": model_config.max_tokens,
            "temperature": model_config.temperature,
            "timeout": model_config.timeout,
            "num_retries": model_config.max_retries,
        }

        if model_config.api_base:
            kwargs["api_base"] = model_config.api_base

        api_key = os.getenv(model_config.api_key_env)
        if api_key:
            kwargs["api_key"] = api_key

        return kwargs

    def get_fallback_models(self, model_name: str) -> list[str]:
        """Get fallback models for a given model."""
        if not self.enable_fallbacks:
            return []

        model_config = self.get_model_config(model_name)
        return model_config.fallback_models


# Default configurations for common providers
DEFAULT_MODELS: dict[str, ModelConfig] = {
    "gpt-4-turbo": ModelConfig(
        model_name="gpt-4-turbo-preview",
        provider="openai",
        api_key_env="OPENAI_API_KEY",
        max_tokens=4096,
        temperature=0.1,
        input_cost_per_1k=0.01,
        output_cost_per_1k=0.03,
        fallback_models=["gpt-4", "gpt-3.5-turbo"],
    ),
    "gpt-4": ModelConfig(
        model_name="gpt-4",
        provider="openai",
        api_key_env="OPENAI_API_KEY",
        max_tokens=8192,
        temperature=0.1,
        input_cost_per_1k=0.03,
        output_cost_per_1k=0.06,
        fallback_models=["gpt-3.5-turbo"],
    ),
    "claude-3-opus": ModelConfig(
        model_name="claude-3-opus-20240229",
        provider="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        max_tokens=4096,
        temperature=0.1,
        input_cost_per_1k=0.015,
        output_cost_per_1k=0.075,
        fallback_models=["claude-3-sonnet-20240229"],
    ),
    "claude-3-sonnet": ModelConfig(
        model_name="claude-3-sonnet-20240229",
        provider="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        max_tokens=4096,
        temperature=0.1,
        input_cost_per_1k=0.003,
        output_cost_per_1k=0.015,
        fallback_models=["claude-3-haiku-20240307"],
    ),
    "azure-gpt-4": ModelConfig(
        model_name="azure/gpt-4",
        provider="azure",
        api_key_env="AZURE_API_KEY",
        api_base=os.getenv("AZURE_API_BASE"),
        max_tokens=8192,
        temperature=0.1,
    ),
    "bedrock-claude": ModelConfig(
        model_name="bedrock/anthropic.claude-3-sonnet-20240229-v1:0",
        provider="bedrock",
        api_key_env="AWS_ACCESS_KEY_ID",
        max_tokens=4096,
        temperature=0.1,
    ),
}


def create_default_config() -> LiteLLMConfig:
    """Create a default LiteLLM configuration."""
    return LiteLLMConfig(
        models=DEFAULT_MODELS,
        agent_models=AgentModelMapping(),
    )
