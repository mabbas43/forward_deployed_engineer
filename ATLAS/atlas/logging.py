"""structlog JSON logging, configured once. Every module does `log = get_logger()`."""

import logging
import sys

import structlog

_configured = False


def get_logger(name: str = "atlas"):
    global _configured
    if not _configured:
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
            logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        )
        _configured = True
    return structlog.get_logger(name)
