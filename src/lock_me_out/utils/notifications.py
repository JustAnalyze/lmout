import subprocess
import sys
import pyfiglet
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


def show_touch_grass_popup():
    """Opens a fullscreen terminal popup with a centered, styled message."""
    try:
        # The script to run is now the Python module that handles rendering
        script_cmd = [sys.executable, "-m", "lock_me_out.utils.center_message"]

        # Try common terminals with fullscreen/maximize flags
        terminals = [
            # Use --start-as=fullscreen for modern kitty
            ["kitty", "--start-as=fullscreen", "--title", "TOUCH GRASS"] + script_cmd,
            ["gnome-terminal", "--full-screen", "--"] + script_cmd,
            ["konsole", "--fullscreen", "-e"] + script_cmd,
            ["xfce4-terminal", "--fullscreen", "-e"] + script_cmd,
            # xterm is basic and might not render Rich colors well, but it's a fallback
            ["xterm", "-fullscreen", "-e"] + script_cmd,
        ]

        for cmd in terminals:
            try:
                # Check if the terminal exists first to avoid spamming errors
                if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                    logger.info(f"Launching touch-grass popup via {cmd[0]}")
                    # Log stdout/stderr to a file to debug the popup script
                    with open("/tmp/popup_debug.log", "w") as log_file:
                        subprocess.Popen(cmd, stdout=log_file, stderr=log_file)
                    return
            except Exception as e:
                logger.debug(f"Failed to launch terminal {cmd[0]}: {e}")

        logger.warning("No suitable terminal emulator found to show popup.")
    except Exception as e:
        logger.error(f"Error generating or showing touch-grass popup: {e}")
