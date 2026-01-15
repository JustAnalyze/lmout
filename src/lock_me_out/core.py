import json
import subprocess
import threading
import time
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import psutil
from loguru import logger
from pydantic import BaseModel, Field

from lock_me_out.settings import settings


def parse_time_string(time_str: str) -> datetime:
    """Parses time strings like '8pm', '8:30pm', '20:00', '20:30'."""
    formats = ["%I%p", "%I:%M%p", "%H:%M", "%H:%M:%S"]
    time_str = time_str.lower().replace(" ", "")
    now = datetime.now()
    for fmt in formats:
        try:
            parsed_time = datetime.strptime(time_str, fmt).time()
            return datetime.combine(now.date(), parsed_time)
        except ValueError:
            continue
    raise ValueError(f"Could not parse time: {time_str}")


def calculate_from_range(
    start_str: str, end_str: str, now: datetime | None = None
) -> tuple[int, int]:
    """
    Calculates delay_seconds and duration_seconds from a time range.
    Returns (delay_seconds, duration_seconds).
    """
    if now is None:
        now = datetime.now()

    start_dt = parse_time_string(start_str)
    end_dt = parse_time_string(end_str)

    # Ensure start/end match the reference date
    start_dt = datetime.combine(now.date(), start_dt.time())
    end_dt = datetime.combine(now.date(), end_dt.time())

    # If end is before start, assume end is tomorrow
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    # Logic for when to start
    if start_dt < now and end_dt > now:
        # We are already in the time range, start immediately
        delay_seconds = 0
        duration_seconds = max(1, int((end_dt - now).total_seconds()))
    elif start_dt >= now:
        # Start in the future
        delay_seconds = int((start_dt - now).total_seconds())
        duration_seconds = max(1, int((end_dt - start_dt).total_seconds()))
    else:
        # Both start and end in the past, assume tomorrow
        start_dt += timedelta(days=1)
        end_dt += timedelta(days=1)
        delay_seconds = int((start_dt - now).total_seconds())
        duration_seconds = max(1, int((end_dt - start_dt).total_seconds()))

    return delay_seconds, duration_seconds


class LockOutManager:
    """
    Manages the lockout logic:
    1. Waits for initial delay.
    2. Sends warnings.
    3. Kills specific processes.
    4. Enforces screen lock for a duration.
    """

    def __init__(self, initial_delay_seconds: int, lockout_duration_seconds: int):
        self.initial_delay_seconds = initial_delay_seconds
        self.lockout_duration_seconds = lockout_duration_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._state = "IDLE"  # IDLE, WAITING, LOCKED
        self._target_end_time = 0.0
        self.blocked_apps: list[str] = []
        self.block_only: bool = False

    def get_status(self):
        """Returns the current status of the manager."""
        remaining = 0
        if self._state != "IDLE" and self._target_end_time > 0:
            remaining = max(0, int(self._target_end_time - time.time()))

        return {"state": self._state, "time_remaining": remaining}

    def start(self, blocked_apps: list[str] | None = None, block_only: bool = False):
        """Starts the lockout process in a background thread."""
        if self._running:
            logger.warning("LockOutManager is already running.")
            return

        self.blocked_apps = blocked_apps or []
        self.block_only = block_only

        logger.info(
            f"Starting LockOutManager: Delay={self.initial_delay_seconds}s, "
            f"Duration={self.lockout_duration_seconds}s, "
            f"BlockOnly={self.block_only}, Apps={self.blocked_apps}"
        )
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stops the lockout process."""
        if not self._running:
            return

        logger.info("Stopping LockOutManager...")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._running = False
        self._state = "IDLE"
        logger.info("LockOutManager stopped.")

    def _run(self):
        """Main logic loop running in the thread."""
        try:
            self._wait_initial_delay()
            if self._stop_event.is_set():
                return

            self._perform_lockout()

        except Exception as e:
            logger.exception(f"Error in LockOutManager: {e}")
        finally:
            self._running = False
            self._state = "IDLE"

    def _wait_initial_delay(self):
        """Waits for the initial delay, sending notifications."""
        logger.info("Waiting for initial delay...")
        self._state = "WAITING"
        start_time = time.time()
        self._target_end_time = start_time + self.initial_delay_seconds
        end_time = self._target_end_time

        # Check every second
        while time.time() < end_time:
            if self._stop_event.is_set():
                return

            remaining = end_time - time.time()

            # Warning at 1 minute (check roughly within a 1s window)
            if 60 <= remaining < 61:
                self._send_notification(
                    "1 minute remaining before lockout.", "MAKE SURE TO REST!"
                )

            time.sleep(1)

    def _perform_lockout(self):
        """Executes the lockout phase."""
        logger.info("Initial delay complete. Initiating lockout.")
        self._state = "LOCKED"

        start_time = time.time()
        self._target_end_time = start_time + self.lockout_duration_seconds
        end_time = self._target_end_time

        while time.time() < end_time:
            if self._stop_event.is_set():
                return

            # Kill specific blocked apps
            for app_name in self.blocked_apps:
                self._kill_process(app_name, app_name)

            # Check and lock screen (if not block-only)
            if not self.block_only:
                if not self._is_screen_locked():
                    self._lock_screen()

            time.sleep(2)

        if not self._stop_event.is_set():
            logger.info("Lockout duration finished.")
            self._send_notification("Lockout Finished", "You can now resume your work.")

    def _kill_process(self, process_name: str, display_name: str):
        """Kills a process by name if it's running."""
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
            self._send_notification(
                f"Blocked {display_name}", "App closed per schedule."
            )

    def _send_notification(self, summary: str, body: str):
        """Sends a desktop notification."""
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

    def _is_screen_locked(self) -> bool:
        """Checks if the screen is locked using available tools."""
        # This is a bit tricky across DEs. Original script grep'd xdg-screensaver status
        try:
            # Try xdg-screensaver first
            result = subprocess.run(
                ["xdg-screensaver", "status"], capture_output=True, text=True
            )
            if "is locked" in result.stdout:
                return True

            # Fallback/Alternative check using loginctl?
            # loginctl show-session-property properties 'LockedHint' but need
            # session ID. Sticking to the user's script logic for now which
            # relied on xdg-screensaver

            return False
        except FileNotFoundError:
            logger.warning("xdg-screensaver not found.")
            return False

    def _lock_screen(self):
        """Locks the screen."""
        logger.debug("Locking screen...")
        try:
            subprocess.run(["xdg-screensaver", "lock"], check=False)

            # Fallback mentioned in script: loginctl lock-session
            # subprocess.run(["loginctl", "lock-session"], check=False)
        except FileNotFoundError:
            pass


class LockSchedule(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    start_time: str
    end_time: str
    enabled: bool = True
    description: str | None = None
    persist: bool = False
    notified_5m: bool = False  # Track if we already sent the 5-minute warning
    blocked_apps: list[str] = Field(default_factory=list)
    block_only: bool = False


class ScheduleManager:
    """Manages multiple schedules and their persistence."""

    def __init__(self):
        self.schedules_file = settings.data_dir / "schedules.json"
        self.schedules: list[LockSchedule] = []
        self._load_schedules()

    def send_notification(self, summary: str, body: str):
        """Sends a desktop notification (duplicated from LockOutManager for convenience)."""
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
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")

    def _load_schedules(self):
        if not self.schedules_file.exists():
            self.schedules = []
            return

        try:
            with open(self.schedules_file) as f:
                data = json.load(f)
                self.schedules = [LockSchedule(**s) for s in data]
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Failed to load schedules: {e}")
            self.schedules = []

    def save_schedules(self):
        try:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.schedules_file, "w") as f:
                json.dump(
                    [s.model_dump(mode="json") for s in self.schedules],
                    f,
                    indent=4,
                )
        except Exception as e:
            logger.error(f"Failed to save schedules: {e}")

    def add_schedule(
        self,
        start_time: str,
        end_time: str,
        description: str = "",
        persist: bool = False,
        blocked_apps: list[str] | None = None,
        block_only: bool = False,
    ) -> LockSchedule:
        schedule = LockSchedule(
            start_time=start_time,
            end_time=end_time,
            description=description,
            persist=persist,
            blocked_apps=blocked_apps or [],
            block_only=block_only,
        )
        self.schedules.append(schedule)
        self.save_schedules()
        return schedule

    def remove_schedule(self, schedule_id: UUID):
        self.schedules = [s for s in self.schedules if s.id != schedule_id]
        self.save_schedules()

    def update_schedule(self, schedule: LockSchedule):
        for i, s in enumerate(self.schedules):
            if s.id == schedule.id:
                self.schedules[i] = schedule
                break
        self.save_schedules()

    def check_schedules(self) -> list[tuple[LockSchedule, int, int]]:
        """
        Returns a list of (schedule, delay_seconds, duration_seconds) for schedules.
        Sorted by delay (ascending), so active schedules (delay 0) come first,
        followed by nearest future schedules.
        """
        candidates = []
        for s in self.schedules:
            if not s.enabled:
                continue
            try:
                # Reuse calculate_from_range to handle today/tomorrow logic
                delay, duration = calculate_from_range(s.start_time, s.end_time)
                candidates.append((s, delay, duration))
            except Exception:
                continue

        # Sort by delay so that active (0) or nearest future comes first
        candidates.sort(key=lambda x: x[1])
        return candidates
