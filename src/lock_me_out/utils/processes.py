import subprocess

import psutil
from loguru import logger

from lock_me_out.utils.notifications import send_notification


def kill_process(process_name: str, display_name: str | None = None):
    """Kills a process by name if it's running."""
    display_name = display_name or process_name
    killed = False
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] == process_name:
                logger.info(f"Killing {process_name} (PID: {proc.pid})")
                proc.kill()
                killed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if killed:
        send_notification(f"Blocked {display_name}", "App closed per schedule.")


def is_screen_locked() -> bool:
    """Checks if the screen is locked using xdg-screensaver."""
    try:
        result = subprocess.run(
            ["xdg-screensaver", "status"], capture_output=True, text=True
        )
        return "is locked" in result.stdout
    except FileNotFoundError:
        logger.warning("xdg-screensaver not found.")
        return False


def lock_screen():
    """Locks the screen using xdg-screensaver."""
    logger.debug("Locking screen...")
    try:
        subprocess.run(["xdg-screensaver", "lock"], check=False)
    except FileNotFoundError:
        logger.warning("xdg-screensaver not found.")
