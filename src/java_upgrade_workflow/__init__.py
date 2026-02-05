"""
Java Upgrade Workflow - LangGraph Multi-Agent System

A comprehensive workflow system for upgrading Java and Spring Boot applications
using LangGraph orchestration with LiteLLM for externalized LLM configuration.
"""

__version__ = "1.0.0"
__author__ = "Java Upgrade Team"

from java_upgrade_workflow.workflow import JavaUpgradeWorkflow
from java_upgrade_workflow.state.upgrade_state import UpgradeState

__all__ = ["JavaUpgradeWorkflow", "UpgradeState", "__version__"]
