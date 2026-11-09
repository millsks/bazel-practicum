"""Structured logging configuration for the practicum CLI."""

import sys

import structlog


def configure_logging(*, json: bool = False) -> None:
    """Configure structlog for key=value console output or JSON output.

    Args:
        json: Render each event as a JSON object instead of key=value pairs.
    """
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            renderer,
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )


def get_logger() -> structlog.typing.FilteringBoundLogger:
    """Return the practicum logger.

    Returns:
        A bound structlog logger.
    """
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger("practicum")
    return logger
