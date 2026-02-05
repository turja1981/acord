"""
Logging utilities for Java Upgrade Workflow.
"""

import logging
import sys
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    rich_output: bool = True,
) -> None:
    """
    Set up logging configuration.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional file path for log output
        rich_output: Use rich console handler for prettier output
    """
    handlers = []

    if rich_output:
        console = Console(stderr=True)
        handlers.append(
            RichHandler(
                console=console,
                show_time=True,
                show_path=False,
                markup=True,
            )
        )
    else:
        handlers.append(logging.StreamHandler(sys.stderr))

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        )
        handlers.append(file_handler)

    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(message)s",
        datefmt="[%X]",
        handlers=handlers,
    )


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name."""
    return logging.getLogger(name)
