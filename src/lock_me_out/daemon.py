import time
from datetime import datetime

from rich.console import Console

from lock_me_out.manager import LockOutManager, ScheduleManager
from lock_me_out.settings import load_settings
from lock_me_out.utils.state import write_state, cleanup_state

console = Console()


def run_daemon():
    """Main loop for the lockout daemon."""
    sm = ScheduleManager()
    console.print("[bold green]Lock Me Out daemon started...[/bold green]")
    console.print("Checking schedules every 30 seconds. Press Ctrl+C to stop.")

    current_manager: LockOutManager | None = None
    active_sched_id: str | None = None

    # Initial state write
    write_state()

    try:
        while True:
            # Update state with current info
            active_info = None
            if current_manager and current_manager.get_status()["state"] != "IDLE":
                status = current_manager.get_status()
                active_info = {
                    "duration_mins": current_manager.lockout_duration_seconds // 60,
                    "start_time": datetime.now().strftime("%I:%M%p"),
                    "block_only": current_manager.block_only,
                    "blocked_apps": current_manager.blocked_apps,
                    "remaining_secs": status["time_remaining"],
                }
            write_state(active_info)

            # Reload schedules and settings
            sm._load_schedules()
            current_settings = load_settings()

            # Handle transitions when a lockout finishes
            if current_manager and current_manager.get_status()["state"] == "IDLE":
                if active_sched_id:
                    finished_sched = next(
                        (s for s in sm.schedules if str(s.id) == active_sched_id), None
                    )
                    if finished_sched and not finished_sched.persist:
                        console.print(
                            f"[dim]Removing finished one-time schedule: "
                            f"{finished_sched.start_time}[/dim]"
                        )
                        sm.remove_schedule(finished_sched.id)
                current_manager = None
                active_sched_id = None

            # If a lockout is already running, just wait
            if current_manager and current_manager.get_status()["state"] != "IDLE":
                time.sleep(5)
                continue

            # Check for any schedules that should be active
            candidates = sm.check_schedules()
            lead_secs = current_settings.notify_lead_minutes * 60

            if candidates:
                sched, delay_secs, duration_secs = candidates[0]

                # Start the manager if we are within the lead time (plus a small buffer)
                if delay_secs < lead_secs + 30:
                    console.print(
                        f"[bold yellow]Preparing scheduled lockout:[/bold yellow] "
                        f"{sched.start_time} - {sched.end_time}"
                    )

                    # Prepare notification
                    summary = current_settings.notify_summary.format(
                        minutes=current_settings.notify_lead_minutes
                    )
                    body = current_settings.notify_body.format(
                        start_time=sched.start_time
                    )

                    current_manager = LockOutManager(delay_secs, duration_secs)
                    active_sched_id = str(sched.id)
                    current_manager.start(
                        blocked_apps=sched.blocked_apps,
                        block_only=sched.block_only,
                        start_notification=(summary, body),
                    )

            time.sleep(30)
    finally:
        console.print("\n[yellow]Stopping daemon...[/yellow]")
        if current_manager:
            current_manager.stop()
        cleanup_state()
