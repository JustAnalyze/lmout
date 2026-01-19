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
    """Checks if the screen is locked using multiple methods."""
    # Method 1: xdg-screensaver
    try:
        result = subprocess.run(
            ["xdg-screensaver", "status"], capture_output=True, text=True, timeout=2
        )
        if "is locked" in result.stdout:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Method 2: loginctl
    try:
        result = subprocess.run(
            ["loginctl", "show-session", "self", "-p", "LockedHint", "--value"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.stdout.strip() == "yes":
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return False


def lock_screen():
    """Locks the screen using multiple methods."""
    logger.debug("Attempting to lock screen...")

    # Method 1: loginctl (Modern systemd way)
    try:
        subprocess.run(["loginctl", "lock-session"], check=False)
    except FileNotFoundError:
        pass

    # Method 2: xdg-screensaver
    try:
        subprocess.run(["xdg-screensaver", "lock"], check=False)
    except FileNotFoundError:
        pass

    # Method 3: gnome-screensaver-command (Specific for GNOME/older systems)
    try:
        subprocess.run(["gnome-screensaver-command", "-l"], check=False)
    except FileNotFoundError:
        pass
