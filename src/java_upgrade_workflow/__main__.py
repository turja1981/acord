"""
Main entry point for the Java Upgrade Workflow package.

This allows running the package as a module:
    python -m java_upgrade_workflow
"""

from java_upgrade_workflow.cli import app

if __name__ == "__main__":
    app()
