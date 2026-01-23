import json
import threading
import time

from loguru import logger

from lock_me_out.schema import LockSchedule
from lock_me_out.settings import settings
from lock_me_out.utils.notifications import send_notification
from lock_me_out.utils.processes import (
    is_screen_locked,
    kill_processes,
    lock_screen,
    wait_for_unlock,
)
from lock_me_out.utils.time import calculate_from_range


class LockOutManager:
    """Manages the lifecycle of a single lockout session."""

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
        self.start_notification: tuple[str, str] | None = None

    def get_status(self):
        """Returns the current status of the manager."""
        remaining = 0
        if self._state != "IDLE" and self._target_end_time > 0:
            remaining = max(0, int(self._target_end_time - time.time()))

        return {"state": self._state, "time_remaining": remaining}

    def start(
        self,
        blocked_apps: list[str] | None = None,
        block_only: bool = False,
        start_notification: tuple[str, str] | None = None,
    ):
        """Starts the lockout process in a background thread."""
        if self._running:
            logger.warning("LockOutManager is already running.")
            return

        self.blocked_apps = blocked_apps or []
        self.block_only = block_only
        self.start_notification = start_notification

        logger.info(
            f"Starting LockOutManager: Delay={self.initial_delay_seconds}s, "
            f"Duration={self.lockout_duration_seconds}s, "
            f"BlockOnly={self.block_only}, Apps={self.blocked_apps}"
        )
        self._stop_event.clear()
        self._running = True
        self._state = "WAITING"
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
        """Waits for the initial delay, sending notifications at milestones."""
        if self.start_notification:
            send_notification(*self.start_notification)

        logger.info("Waiting for initial delay...")

        self._state = "WAITING"
        self._target_end_time = time.time() + self.initial_delay_seconds
        end_time = self._target_end_time

        notified_one_minute = False

        while time.time() < end_time:
            remaining = end_time - time.time()

            if 60 <= remaining < 61 and not notified_one_minute:
                send_notification(
                    "1 minute remaining before lockout.", "MAKE SURE TO REST!"
                )
                notified_one_minute = True

            # Sleep for remaining time or a maximum of 5 seconds to re-check
            sleep_duration = min(remaining, 5.0)
            if sleep_duration <= 0:
                break

            if self._stop_event.wait(timeout=sleep_duration):
                return  # Stop event was set, exit early

    def _perform_lockout(self):
        """Executes the lockout phase (app blocking and screen locking)."""
        logger.info("Initial delay complete. Initiating lockout.")
        self._state = "LOCKED"

        self._target_end_time = time.time() + self.lockout_duration_seconds
        end_time = self._target_end_time

        while time.time() < end_time:
            if self._stop_event.is_set():
                return

            # Kill specific blocked apps
            if self.blocked_apps:
                kill_processes(self.blocked_apps)

            # Check and lock screen (if not block-only)
            if not self.block_only:
                if not is_screen_locked():
                    lock_screen()

            # Smart Wait: If screen is locked, use event monitor (efficient).
            # If not locked (or block-only), poll normally.
            if not self.block_only and is_screen_locked():
                # Wait efficiently for unlock signal or timeout (10s)
                logger.debug("Screen is locked. Entering efficient wait (D-Bus monitor).")
                wait_for_unlock(self._stop_event, timeout=10)
            else:
                # Wait for 2 seconds or until stop event is set
                if self._stop_event.wait(timeout=2):
                    return  # Stop event was set, exit early

        if not self._stop_event.is_set():
            logger.info("Lockout duration finished.")
            send_notification("Lockout Finished", "You can now resume your work.")



class ScheduleManager:
    """Manages persistence and retrieval of lock schedules."""

    def __init__(self):
        self.schedules_file = settings.data_dir / "schedules.json"
        self.schedules: list[LockSchedule] = []
        self._last_schedules_mtime: float | None = None
        self._load_schedules()

    def _load_schedules(self):
        if not self.schedules_file.exists():
            self._last_schedules_mtime = None
            self.schedules = []
            return

        current_mtime = self.schedules_file.stat().st_mtime
        if self._last_schedules_mtime == current_mtime:
            # File hasn't changed, no need to reload
            return

        try:
            with open(self.schedules_file) as f:
                data = json.load(f)
                self.schedules = [LockSchedule(**s) for s in data]
            self._last_schedules_mtime = current_mtime
        except Exception as e:
            logger.error(f"Failed to load schedules: {e}")

    def save_schedules(self):
        """Saves current schedules to JSON."""
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
        """Adds a new schedule and saves it."""
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

    def remove_schedule(self, schedule_id: str):
        """Removes a schedule by ID."""
        self.schedules = [s for s in self.schedules if str(s.id) != str(schedule_id)]
        self.save_schedules()

    def skip_schedule_today(self, schedule_id: str):
        """Adds today's date to the schedule's skipped_dates list."""
        from datetime import date

        today_str = date.today().isoformat()
        for s in self.schedules:
            if str(s.id) == str(schedule_id) and today_str not in s.skipped_dates:
                s.skipped_dates.append(today_str)
                self.save_schedules()
                logger.info(f"Schedule {schedule_id} skipped for today.")
                break

    def reset_skipped_schedules(self):
        """Removes today from all skipped_dates lists."""
        from datetime import date

        today_str = date.today().isoformat()
        updated = False
        for s in self.schedules:
            if today_str in s.skipped_dates:
                s.skipped_dates.remove(today_str)
                updated = True
        if updated:
            self.save_schedules()
            logger.info("Reset skipped dates for today.")

    def update_schedule(self, schedule: LockSchedule):
        """Updates an existing schedule."""
        for i, s in enumerate(self.schedules):
            if s.id == schedule.id:
                self.schedules[i] = schedule
                break
        self.save_schedules()

    def check_schedules(self) -> list[tuple[LockSchedule, int, int, int]]:
        """
        Returns schedules sorted by their next activation delay.
        Includes (schedule, delay, remaining_duration, total_duration).
        """
        from datetime import date

        candidates = []
        today_str = date.today().isoformat()
        for s in self.schedules:
            if not s.enabled or today_str in s.skipped_dates:
                continue
            try:
                delay, duration, total = calculate_from_range(s.start_time, s.end_time)
                candidates.append((s, delay, duration, total))
            except Exception:
                continue

        candidates.sort(key=lambda x: x[1])
        return candidates
