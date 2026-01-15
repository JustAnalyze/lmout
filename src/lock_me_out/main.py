import time
from datetime import datetime

import typer
from rich.console import Console
from rich.table import Table

from lock_me_out.core import LockOutManager, ScheduleManager, calculate_from_range
from lock_me_out.logging_config import setup_logging

app = typer.Typer(help="Lock Me Out - CLI Schedule Manager")
console = Console()


@app.command()
def add(
    start_time: str = typer.Argument(..., help="Start time (e.g. 8pm, 20:00)"),
    end_time: str = typer.Argument(..., help="End time (e.g. 8:30pm, 20:30)"),
    description: str | None = typer.Option(
        None, "--desc", "-d", help="Optional description"
    ),
    persist: bool = typer.Option(
        False, "--persist", "-p", help="Keep schedule after it finishes"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """
    Add a new scheduled lockout.
    """
    setup_logging(verbose=verbose)
    sm = ScheduleManager()

    try:
        # Validate format
        calculate_from_range(start_time, end_time)
        sched = sm.add_schedule(
            start_time, end_time, description or "", persist=persist
        )
        console.print(
            f"[green]Successfully added schedule:[/green] "
            f"{sched.start_time} - {sched.end_time}"
        )
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@app.command()
def start(
    delay: int = typer.Option(30, "--delay", "-d", help="Initial delay in minutes"),
    duration: int = typer.Option(
        10, "--duration", "-l", help="Lockout duration in minutes"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """
    Start an instant lockout session.
    """
    setup_logging(verbose=verbose)
    # Convert minutes to seconds
    manager = LockOutManager(delay * 60, duration * 60)
    console.print(
        f"[bold green]Starting instant lockout...[/bold green] "
        f"Delay: {delay}m, Duration: {duration}m"
    )
    manager.start()

    try:
        while manager._running:
            time.sleep(1)
    except KeyboardInterrupt:
        manager.stop()
        console.print("\n[yellow]Lockout stopped manually.[/yellow]")


@app.command(name="list")
def list_schedules(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """
    List all scheduled lockouts, sorted by soonest first.
    """
    setup_logging(verbose=verbose)
    sm = ScheduleManager()

    # Get schedules with their next activation info
    schedules_with_info = sm.check_schedules()

    if not schedules_with_info:
        console.print("[yellow]No active schedules found.[/yellow]")
        return

    table = Table(title="Scheduled Lockouts (Soonest First)")
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("Start", style="magenta")
    table.add_column("End", style="magenta")
    table.add_column("In (approx)", style="green")
    table.add_column("Duration (m)", style="blue")
    table.add_column("Persist", style="yellow")
    table.add_column("Description", style="white")

    for i, (sched, delay_secs, duration_secs) in enumerate(schedules_with_info, 1):
        # Convert delay to human readable
        if delay_secs == 0:
            in_text = "NOW"
        elif delay_secs < 60:
            in_text = f"{delay_secs}s"
        elif delay_secs < 3600:
            in_text = f"{delay_secs // 60}m"
        else:
            in_text = f"{delay_secs // 3600}h {(delay_secs % 3600) // 60}m"

        table.add_row(
            str(i),
            sched.start_time,
            sched.end_time,
            in_text,
            str(duration_secs // 60),
            "Yes" if sched.persist else "No",
            sched.description or "",
        )

    console.print(table)


@app.command()
def remove(
    index: int = typer.Argument(
        ..., help="Index of the schedule to remove (from lmout list)"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """
    Remove a schedule by its index in the list.
    """
    setup_logging(verbose=verbose)
    sm = ScheduleManager()

    # We need to get the list in the same order as 'list' command
    schedules_with_info = sm.check_schedules()

    if index < 1 or index > len(schedules_with_info):
        console.print(f"[red]Error:[/red] Index {index} is out of range.")
        raise typer.Exit(1) from None

    target_sched, _, _ = schedules_with_info[index - 1]
    sm.remove_schedule(target_sched.id)
    console.print(
        f"[green]Removed schedule:[/green] {target_sched.start_time} - "
        f"{target_sched.end_time}"
    )


@app.command()
def config(
    lead_mins: int | None = typer.Option(
        None, "--lead", "-l", help="Minutes before lockout to notify"
    ),
    summary: str | None = typer.Option(
        None, "--summary", "-s", help="Notification summary (use {minutes})"
    ),
    body: str | None = typer.Option(
        None, "--body", "-b", help="Notification body (use {start_time})"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """
    Configure notification settings.
    """
    from lock_me_out.settings import load_settings

    setup_logging(verbose=verbose)

    # Reload to ensure we have latest
    current_settings = load_settings()

    if lead_mins is not None:
        current_settings.notify_lead_minutes = lead_mins
    if summary is not None:
        current_settings.notify_summary = summary
    if body is not None:
        current_settings.notify_body = body

    current_settings.save()

    table = Table(title="Current Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="magenta")
    table.add_row("Lead Minutes", str(current_settings.notify_lead_minutes))
    table.add_row("Summary Template", current_settings.notify_summary)
    table.add_row("Body Template", current_settings.notify_body)
    console.print(table)
    console.print("[green]Configuration saved![/green]")


@app.command()
def status(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """
    Check the status of the daemon and active lockouts.
    """
    import json
    import os
    import subprocess

    from lock_me_out.settings import settings

    setup_logging(verbose=verbose)

    # 1. Systemd Service Status
    is_active = False
    systemd_pid = None
    try:
        # Check if active
        active_res = subprocess.run(
            ["systemctl", "--user", "is-active", "lmout.service"],
            capture_output=True,
            text=True,
        )
        is_active = active_res.stdout.strip() == "active"

        # Try to get PID from systemd
        if is_active:
            pid_res = subprocess.run(
                [
                    "systemctl",
                    "--user",
                    "show",
                    "lmout.service",
                    "-p",
                    "MainPID",
                    "--value",
                ],
                capture_output=True,
                text=True,
            )
            val = pid_res.stdout.strip()
            if val and val != "0":
                systemd_pid = int(val)
    except Exception:
        pass

    # 2. State File Status
    active_lockout = None
    daemon_pid = None

    if settings.state_file.exists():
        try:
            with open(settings.state_file) as f:
                state = json.load(f)
                daemon_pid = state.get("pid")
                active_lockout = state.get("active_lockout")

            # Verify if the PID is actually running
            if daemon_pid:
                try:
                    os.kill(daemon_pid, 0)
                except OSError:
                    daemon_pid = None  # Stale state file
        except Exception:
            pass

    # Use systemd PID as fallback if state file is missing/stale
    if not daemon_pid and systemd_pid:
        daemon_pid = systemd_pid

    # Display Status
    console.print("[bold cyan]Lock Me Out - Daemon Status[/bold cyan]")

    status_text = (
        "[bold green]● Running[/bold green]"
        if is_active or daemon_pid
        else "[bold red]○ Stopped[/bold red]"
    )
    console.print(f"Service Status: {status_text}")

    if daemon_pid:
        console.print(f"Daemon PID: [magenta]{daemon_pid}[/magenta]")

    if active_lockout:
        console.print("\n[bold yellow]⚠️ ACTIVE LOCKOUT[/bold yellow]")
        console.print(f"Duration: {active_lockout.get('duration_mins')}m")
        console.print(f"Started at: {active_lockout.get('start_time')}")
    else:
        console.print("\nNo lockout currently active.")

    if not is_active and not daemon_pid:
        console.print(
            "\n[dim]To start the daemon, run: [bold]lmout run[/bold] or use systemd.[/dim]"
        )


@app.command()
def run(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """
    Run the lockout daemon to enforce schedules.
    """
    import json
    import os

    from lock_me_out.settings import settings

    setup_logging(verbose=verbose)

    def write_state(active_info=None):
        state = {
            "pid": os.getpid(),
            "last_update": datetime.now().isoformat(),
            "active_lockout": active_info,
        }
        try:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            with open(settings.state_file, "w") as f:
                json.dump(state, f)
        except Exception:
            pass

    def cleanup_state():
        if settings.state_file.exists():
            try:
                settings.state_file.unlink()
            except Exception:
                pass

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
            if current_manager and current_manager._running:
                active_info = {
                    "duration_mins": current_manager.lockout_duration_seconds // 60,
                    "start_time": datetime.now().strftime("%I:%M%p"),  # Rough
                }
            write_state(active_info)
            # Reload schedules and settings in case they were modified externally
            sm._load_schedules()
            from lock_me_out.settings import load_settings

            current_settings = load_settings()

            # Handle transitions when a lockout finishes
            if current_manager and not current_manager._running:
                if active_sched_id:
                    # Find the schedule that just finished
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
            if current_manager and current_manager._running:
                time.sleep(5)
                continue

            # Check for any schedules that should be active
            candidates = sm.check_schedules()

            lead_secs = current_settings.notify_lead_minutes * 60
            for sched, delay_secs, _ in candidates:
                # Notification warning
                # Check if it's within a 1 minute window of the lead time
                if (
                    lead_secs - 30 <= delay_secs <= lead_secs + 30
                    and not sched.notified_5m
                ):
                    summary = current_settings.notify_summary.format(
                        minutes=current_settings.notify_lead_minutes
                    )
                    body = current_settings.notify_body.format(
                        start_time=sched.start_time
                    )
                    sm.send_notification(summary, body)
                    sched.notified_5m = True
                    sm.update_schedule(sched)  # Persist the notified state

            if candidates:
                # The first candidate is the soonest
                sched, delay_secs, duration_secs = candidates[0]

                # If it's time to start (delay is 0 or very small)
                if delay_secs < 30:
                    console.print(
                        f"[bold yellow]Starting scheduled lockout:[/bold yellow] "
                        f"{sched.start_time} - {sched.end_time}"
                    )
                    # Reset notified flag for persistent schedules so they warn next time
                    if sched.persist:
                        sched.notified_5m = False
                        sm.update_schedule(sched)

                    current_manager = LockOutManager(delay_secs, duration_secs)
                    active_sched_id = str(sched.id)
                    current_manager.start()

            time.sleep(30)
    finally:
        console.print("\n[yellow]Stopping daemon...[/yellow]")
        if current_manager:
            current_manager.stop()
        cleanup_state()


@app.callback()
def main():
    """
    Lock Me Out - A CLI tool to manage scheduled screen lockouts.

    Use 'add' to schedule a lockout, 'list' to see them, and 'run' to start the daemon.
    """


if __name__ == "__main__":
    app()
