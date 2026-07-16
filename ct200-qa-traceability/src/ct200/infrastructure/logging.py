"""Structlog configuration for the CT200 QA Traceability System.

Configures structured JSON logging with:
- Correlation ID binding via contextvars (merged into every log entry)
- ISO 8601 timestamps
- Log level and logger name in every entry
- Standard library integration so third-party logs also get structured
"""

import logging
import sys

import structlog


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog for structured JSON logging.

    Sets up:
    - JSON rendering for all log output
    - Correlation ID binding via contextvars (merged from CorrelationMiddleware)
    - Timestamp (ISO 8601), log level, and logger name in every entry
    - Standard library integration so third-party logs also get structured
    - Exception info rendering

    Args:
        log_level: The minimum log level to emit (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    # Processors shared between structlog loggers and stdlib loggers
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # ProcessorFormatter handles final rendering for all stdlib-routed log records.
    # foreign_pre_chain processes log records from stdlib loggers that didn't go
    # through structlog (e.g., uvicorn, sqlalchemy).
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
