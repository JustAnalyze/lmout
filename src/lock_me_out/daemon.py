import time
from datetime import datetime, timedelta
import json

from rich.console import Console

from lock_me_out.manager import LockOutManager, ScheduleManager
from lock_me_out.settings import load_settings, settings
from lock_me_out.utils.state import write_state, cleanup_state

console = Console()


def _process_commands() -> tuple[LockOutManager | None, str | None, dict | None]:
    """
    Checks for and processes a command from the command file.

    Returns:
        A tuple containing (manager, schedule_id, extra_data) if a valid
        command was processed, otherwise (None, None, None).
    """
    if not settings.command_file.exists():
        return None, None, None

    try:
        with open(settings.command_file) as f:
            command_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        console.print(f"[red]Error reading command file: {e}[/red]")
        settings.command_file.unlink()
        return None, None, None
    finally:
        if settings.command_file.exists():
            settings.command_file.unlink()

    cmd = command_data.get("command")
    if cmd == "start_instant":
        console.print("[bold blue]Received command to start instant lockout.[/bold blue]")
        delay_mins = command_data.get("delay_mins", 30)
        duration_mins = command_data.get("duration_mins", 10)
        blocked_apps = command_data.get("blocked_apps", [])
        block_only = command_data.get("block_only", False)

        manager = LockOutManager(delay_mins * 60, duration_mins * 60)
        manager.start(blocked_apps=blocked_apps, block_only=block_only)

        # Data for state reporting
        instant_data = {
            "duration_mins": duration_mins,
            "start_time": (datetime.now() + timedelta(minutes=delay_mins)).strftime(
                "%I:%M%p"
            ),
            "block_only": block_only,
            "blocked_apps": blocked_apps,
        }
        return manager, "instant", instant_data

    return None, None, None


def run_daemon():
    """Main loop for the lockout daemon."""
    sm = ScheduleManager()
    console.print("[bold green]Lock Me Out daemon started...[/bold green]")
    console.print("Checking for schedules and commands. Press Ctrl+C to stop.")

    current_manager: LockOutManager | None = None
    active_sched_id: str | None = None
    instant_lockout_data: dict | None = None

    write_state()

    try:
        while True:
            # --- Command & Schedule Processing ---
            is_idle = not current_manager or (
                current_manager.get_status()["state"] == "IDLE"
            )

            if is_idle:
                # 1. Clear previous finished session
                if active_sched_id:
                    if active_sched_id != "instant":
                        finished_sched = next(
                            (s for s in sm.schedules if str(s.id) == active_sched_id),
                            None,
                        )
                        if finished_sched and not finished_sched.persist:
                            console.print(
                                f"[dim]Removing finished one-time schedule: "
                                f"{finished_sched.start_time}[/dim]"
                            )
                            sm.remove_schedule(finished_sched.id)
                    current_manager = None
                    active_sched_id = None
                    instant_lockout_data = None

                # 2. Check for new commands (e.g., lmout start)
                new_manager, new_id, extra_data = _process_commands()
                if new_manager:
                    current_manager = new_manager
                    active_sched_id = new_id
                    instant_lockout_data = extra_data
                else:
                    # 3. Check for upcoming scheduled lockouts
                    sm._load_schedules()
                    current_settings = load_settings()
                    candidates = sm.check_schedules()
                    lead_secs = current_settings.notify_lead_minutes * 60

                    if candidates:
                        sched, delay_secs, duration_secs = candidates[0]
                        if delay_secs < lead_secs + 30:
                            console.print(
                                f"[bold yellow]Preparing scheduled lockout:[/bold yellow] "
                                f"{sched.start_time} - {sched.end_time}"
                            )
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

            # --- State Reporting ---
            active_info = None
            if current_manager and current_manager.get_status()["state"] != "IDLE":
                status = current_manager.get_status()
                is_instant = active_sched_id == "instant"

                if is_instant and instant_lockout_data:
                    active_info = {
                        "source": "instant",
                        "schedule_id": None,
                        "current_phase": status["state"],
                        "remaining_secs": status["time_remaining"],
                        **instant_lockout_data,
                    }
                elif not is_instant:
                    sched = next(
                        (s for s in sm.schedules if str(s.id) == active_sched_id), None
                    )
                    if sched:
                        active_info = {
                            "source": "schedule",
                            "schedule_id": active_sched_id,
                            "current_phase": status["state"],
                            "start_time": sched.start_time,
                            "end_time": sched.end_time,
                            "duration_mins": current_manager.lockout_duration_seconds
                            // 60,
                            "block_only": sched.block_only,
                            "blocked_apps": sched.blocked_apps,
                            "remaining_secs": status["time_remaining"],
                        }
            write_state(active_info)

            time.sleep(5)
    finally:
        console.print("\n[yellow]Stopping daemon...[/yellow]")
        if current_manager:
            current_manager.stop()
        cleanup_state()
