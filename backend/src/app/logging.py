import logging
import sys

from app.core.config import settings

# Configure logging
LOG_LEVEL_MAP = {
    "local": logging.DEBUG,
    "staging": logging.INFO,
    "production": logging.WARNING,
}

# Set the logging level based on the ENVIRONMENT setting
log_level = LOG_LEVEL_MAP.get(settings.ENVIRONMENT, logging.INFO)

logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the specified name.

    Args:
        name: The name for the logger (typically __name__ of the calling module).

    Returns:
        A configured logger instance.
    """
    return logging.getLogger(name)
