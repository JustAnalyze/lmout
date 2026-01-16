import subprocess

from loguru import logger

from lock_me_out.settings import settings


def send_notification(summary: str, body: str):
    """Sends a desktop notification using notify-send."""
    logger.info(f"Sending notification: {summary} | {body}")
    cmd = [
        "notify-send",
        summary,
        body,
        "-a",
        settings.app_name,
        "-i",
        settings.icon_path,
    ]
    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        logger.error("notify-send not found. Install libnotify-bin.")
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")
