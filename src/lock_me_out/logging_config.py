import sys

from loguru import logger

from lock_me_out.settings import settings

# Logging Constants
LOG_FORMAT_CONSOLE = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<level>{message}</level>"
)
LOG_FORMAT_FILE = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}"
LOG_ROTATION = "10 MB"
LOG_RETENTION = "10 days"
LOG_COMPRESSION = "zip"


def setup_logging(verbose: bool = False) -> None:
    """
    Configure the logging system for the application.

    Args:
        verbose (bool): If True, enables DEBUG level logging to stderr.
                       Otherwise, defaults to INFO (unless configured via settings).
    """
    logger.remove()

    is_debug = verbose or settings.debug
    level = "DEBUG" if is_debug else "INFO"

    # 1. Console Sink
    logger.add(sys.stderr, level=level, format=LOG_FORMAT_CONSOLE)

    # 2. File Sink
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = settings.log_dir / "app.log"
    logger.add(
        log_file_path,
        level=level,
        format=LOG_FORMAT_FILE,
        rotation=LOG_ROTATION,
        retention=LOG_RETENTION,
        compression=LOG_COMPRESSION,
    )

    logger.debug(f"Logging initialized. Logs saved to: {log_file_path}")
