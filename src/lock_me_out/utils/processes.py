import select
import subprocess
import threading
import time

import psutil
from loguru import logger

from lock_me_out.utils.notifications import send_notification, show_touch_grass_popup


def kill_processes(process_names: list[str]):
    """Kills a list of processes by name if they are running."""
    killed_processes = set()
    process_names_set = set(process_names)

    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] in process_names_set:
                logger.info(f"Killing {proc.info['name']} (PID: {proc.pid})")
                proc.kill()
                killed_processes.add(proc.info["name"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    for killed_name in killed_processes:
        send_notification(f"Blocked {killed_name}", "App closed per schedule.")


_screen_lock_method_cache: str | None = None


def is_screen_locked() -> bool:
    """Checks if the screen is locked using multiple methods."""
    global _screen_lock_method_cache

    # Prioritize cached method
    if _screen_lock_method_cache == "xdg-screensaver":
        try:
            result = subprocess.run(
                ["xdg-screensaver", "status"], capture_output=True, text=True, timeout=2
            )
            if "is locked" in result.stdout:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            _screen_lock_method_cache = None  # Invalidate cache if it failed
    elif _screen_lock_method_cache == "loginctl":
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
            _screen_lock_method_cache = None  # Invalidate cache if it failed
    elif _screen_lock_method_cache == "gdbus-gnome":
        try:
            result = subprocess.run(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.gnome.ScreenSaver",
                    "--object-path",
                    "/org/gnome/ScreenSaver",
                    "--method",
                    "org.gnome.ScreenSaver.GetActive",
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if "(true,)" in result.stdout:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            _screen_lock_method_cache = None

    # Fallback to other methods if cached method failed or not set
    if _screen_lock_method_cache is None:
        # Method 1: xdg-screensaver
        try:
            result = subprocess.run(
                ["xdg-screensaver", "status"], capture_output=True, text=True, timeout=2
            )
            if "is locked" in result.stdout:
                _screen_lock_method_cache = "xdg-screensaver"
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
                _screen_lock_method_cache = "loginctl"
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Method 3: gdbus (GNOME/Cinnamon/MATE)
        try:
            result = subprocess.run(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.gnome.ScreenSaver",
                    "--object-path",
                    "/org/gnome/ScreenSaver",
                    "--method",
                    "org.gnome.ScreenSaver.GetActive",
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if "(true,)" in result.stdout:
                _screen_lock_method_cache = "gdbus-gnome"
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return False


_screen_lock_command_cache: list[str] | None = None


def lock_screen():
    """Locks the screen using multiple methods."""
    global _screen_lock_command_cache
    logger.debug("Attempting to lock screen...")

    # Prioritize cached command
    if _screen_lock_command_cache:
        try:
            subprocess.run(_screen_lock_command_cache, check=False)
            return  # If cached command worked, we're done
        except FileNotFoundError:
            _screen_lock_command_cache = None  # Invalidate cache if it failed

    # Fallback to other methods if cached command failed or not set
    # Method 1: loginctl (Modern systemd way)
    try:
        command = ["loginctl", "lock-session"]
        subprocess.run(command, check=False)
        _screen_lock_command_cache = command
        return
    except FileNotFoundError:
        pass

    # Method 2: xdg-screensaver
    try:
        command = ["xdg-screensaver", "lock"]
        subprocess.run(command, check=False)
        _screen_lock_command_cache = command
        return
    except FileNotFoundError:
        pass

    # Method 3: gnome-screensaver-command (Specific for GNOME/older systems)
    try:
        command = ["gnome-screensaver-command", "-l"]
        subprocess.run(command, check=False)
        _screen_lock_command_cache = command
        return
    except FileNotFoundError:
        pass


def wait_for_unlock(stop_event: threading.Event, timeout: float = 60.0):
    """
    Waits efficiently for the screen to be unlocked.
    Uses dbus-monitor to avoid polling if possible.
    Returns when screen is unlocked, timeout expires, or stop_event is set.
    """
    start_time = time.time()
    proc = None

    # Try dbus-monitor for GNOME/MATE (ActiveChanged signal)
    # We could also add org.freedesktop.ScreenSaver but it often requires different handling.
    # We assume if is_screen_locked works via gdbus-gnome, this works too.
    try:
        # Monitoring generic GNOME screensaver signals
        proc = subprocess.Popen(
            [
                "dbus-monitor",
                "--session",
                "type='signal',interface='org.gnome.ScreenSaver',member='ActiveChanged'",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,  # Line buffered
        )
    except FileNotFoundError:
        proc = None

    if proc:
        logger.debug("Starting dbus-monitor to watch for unlock signal...")
        try:
            while not stop_event.is_set() and (time.time() - start_time < timeout):
                # Check for output with timeout
                rlist, _, _ = select.select([proc.stdout], [], [], 1.0)  # 1s timeout
                if rlist:
                    line = proc.stdout.readline()
                    # GNOME emits ActiveChanged (boolean false) when unlocking
                    if "boolean false" in line:
                        logger.info("D-Bus monitor detected screen unlock signal.")
                        show_touch_grass_popup()
                        # Allow 3 seconds for the user to read the fullscreen message
                        time.sleep(3)
                        return

                # Verify process is still alive
                if proc.poll() is not None:
                    break
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
            return

    # Fallback: Sleep if dbus-monitor not available or failed
    # We loop for 'timeout' seconds, checking stop_event.
    # The caller (manager) will re-check is_screen_locked() after this returns.
    end_time = start_time + timeout
    while not stop_event.is_set() and time.time() < end_time:
        if stop_event.wait(timeout=2):
            return

