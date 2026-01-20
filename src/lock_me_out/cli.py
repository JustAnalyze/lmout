import os
import sys
import subprocess
import time
import json
from datetime import datetime, timedelta
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from lock_me_out.utils.logging import setup_logging
from lock_me_out.manager import LockOutManager, ScheduleManager
from lock_me_out.settings import load_settings, settings
from lock_me_out.utils.time import calculate_from_range, format_duration_seconds
from lock_me_out.utils.state import write_state, cleanup_state


app = typer.Typer(help="Lock Me Out - CLI Schedule Manager")
console = Console()


def is_daemon_running() -> bool:
    """Checks if the daemon is running via state file and PID."""
    if not settings.state_file.exists():
        return False
    try:
        with open(settings.state_file) as f:
            state = json.load(f)
            pid = state.get("pid")
            if not pid:
                return False
            os.kill(pid, 0)  # Check if process exists
            return True
    except (OSError, json.JSONDecodeError, FileNotFoundError):
        return False


def process_apps_list(apps: list[str] | None) -> list[str]:
    """Processes a list of strings potentially containing commas into a clean list of app names."""
    if not apps:
        return []
    processed = []
    for a in apps:
        parts = [x.strip() for x in a.split(",") if x.strip()]
        processed.extend(parts)
    return processed


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
    apps: list[str] | None = typer.Option(
        None, "--apps", "-a", help="Specific apps to block (comma separated names)"
    ),
    block_only: bool = typer.Option(
        False, "--block-only", help="Block apps without locking the screen"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Add a new scheduled lockout."""
    setup_logging(verbose=verbose)
    sm = ScheduleManager()

    processed_apps = process_apps_list(apps)
    blocked_apps = processed_apps if processed_apps else settings.blocked_apps

    try:
        _, _, total_duration_secs = calculate_from_range(start_time, end_time)
        total_duration_mins = total_duration_secs // 60

        if total_duration_mins > settings.MAX_LOCKOUT_MINUTES:
            console.print(
                f"[red]Error:[/red] Scheduled lockout duration ({total_duration_mins}m) "
                f"exceeds the maximum allowed ({settings.MAX_LOCKOUT_MINUTES}m). "
                "This is a guardrail to prevent permanent lockouts."
            )
            raise typer.Exit(1)

        sched = sm.add_schedule(
            start_time,
            end_time,
            description or "",
            persist=persist,
            blocked_apps=blocked_apps,
            block_only=block_only,
        )
        console.print(
            f"[green]Successfully added schedule:[/green] "
            f"{sched.start_time} - {sched.end_time}"
        )
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@app.command(name="instant")
def instant(
    delay: int = typer.Option(30, "--delay", "-d", help="Initial delay in minutes"),
    duration: int = typer.Option(
        10, "--duration", "-l", help="Lockout duration in minutes"
    ),
    apps: list[str] | None = typer.Option(
        None, "--apps", "-a", help="Specific apps to block"
    ),
    block_only: bool = typer.Option(
        False, "--block-only", help="Block apps without locking the screen"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Start an instant lockout session via the running daemon."""
    setup_logging(verbose=verbose)

    if not is_daemon_running():
        console.print(
            "[red]Error:[/red] Daemon is not running. Please start it with `lmout start`."
        )
        raise typer.Exit(1)

    if settings.command_file.exists():
        # Check if the file is stale (older than 30 seconds)
        mtime = settings.command_file.stat().st_mtime
        if time.time() - mtime > 30:
            console.print("[yellow]Found stale command file, removing...[/yellow]")
            settings.command_file.unlink()
        else:
            console.print(
                f"[yellow]Warning:[/yellow] Another command is already pending (at {settings.command_file}). "
                "Please wait a moment before trying again."
            )
            raise typer.Exit(1)
    
    if duration > settings.MAX_LOCKOUT_MINUTES:
        console.print(
            f"[red]Error:[/red] Instant lockout duration ({duration}m) "
            f"exceeds the maximum allowed ({settings.MAX_LOCKOUT_MINUTES}m). "
            "This is a guardrail to prevent permanent lockouts."
        )
        raise typer.Exit(1)

    processed_apps = process_apps_list(apps)
    blocked_apps = processed_apps if processed_apps else settings.blocked_apps

    command = {
        "command": "start_instant",
        "delay_mins": delay,
        "duration_mins": duration,
        "blocked_apps": blocked_apps,
        "block_only": block_only,
    }

    try:
        # This is an atomic operation on most OSes.
        with open(settings.command_file, "w") as f:
            json.dump(command, f)
    except IOError as e:
        console.print(f"[red]Error:[/red] Could not send command to daemon: {e}")
        raise typer.Exit(1)

    mode_text = "App Blocking" if block_only else "Full Lockout"
    console.print(
        f"[bold green]Requesting instant {mode_text}...[/bold green] "
        f"Delay: {delay}m, Duration: {duration}m"
    )
    if blocked_apps:
        console.print(f"Blocking apps: [magenta]{', '.join(blocked_apps)}[/magenta]")


@app.command(name="list")
def list_schedules(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """List all scheduled and active instant lockouts."""
    setup_logging(verbose=verbose)
    sm = ScheduleManager()
    schedules_with_info = sm.check_schedules()
    all_rows = []

    # Check for an active lockout from the state file
    active_lockout = None
    if settings.state_file.exists():
        try:
            with open(settings.state_file) as f:
                state = json.load(f)
                active_lockout = state.get("active_lockout")
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    active_sched_id = active_lockout.get("schedule_id") if active_lockout else None

    # 1. Process scheduled lockouts
    for i, (sched, delay_secs, duration_secs, total_secs) in enumerate(schedules_with_info, 1):
        is_active = active_sched_id and str(sched.id) == str(active_sched_id)
        
        if is_active:
            # This schedule is currently active, we'll combine info
            rem_secs = active_lockout.get("remaining_secs", 0)
            current_phase = active_lockout.get("current_phase")
            if current_phase == "WAITING":
                in_text = f"Starts in {rem_secs // 60}m" if rem_secs > 60 else f"Starts in {rem_secs}s"
            else:
                in_text = f"Ends in {rem_secs // 60}m" if rem_secs > 60 else f"Ends in {rem_secs}s"
            
            indicator = f"S{i}"
        else:
            if delay_secs < 60:
                in_text = f"{delay_secs}s" if delay_secs > 0 else "NOW"
            elif delay_secs < 3600:
                in_text = f"{delay_secs // 60}m"
            else:
                in_text = f"{delay_secs // 3600}h {(delay_secs % 3600) // 60}m"
            indicator = str(i)

        mode = "Apps Only" if sched.block_only else "Full Lock"
        blocked_apps = ", ".join(sched.blocked_apps) if sched.blocked_apps else "None"
        
        all_rows.append(
            (
                -1 if is_active else delay_secs,
                indicator,
                sched.start_time,
                sched.end_time,
                in_text,
                format_duration_seconds(total_secs),
                mode,
                blocked_apps,
                "Yes" if sched.persist else "No",
                sched.description or "Scheduled",
            )
        )

    # 2. Check for an active lockout that is NOT from a schedule (e.g. instant)
    if active_lockout and not active_sched_id:
        rem_secs = active_lockout.get("remaining_secs", 0)
        current_phase = active_lockout.get("current_phase")

        if current_phase == "WAITING":
            in_text = (
                f"Starts in {rem_secs // 60}m"
                if rem_secs > 60
                else f"Starts in {rem_secs}s"
            )
        elif current_phase == "LOCKED":
            in_text = (
                f"Ends in {rem_secs // 60}m"
                if rem_secs > 60
                else f"Ends in {rem_secs}s"
            )
        else:
            in_text = "N/A"
        
        mode = "Apps Only" if active_lockout.get("block_only") else "Full Lock"
        apps = active_lockout.get("blocked_apps", [])
        blocked_apps_str = ", ".join(apps) if apps else "None"

        is_instant = active_lockout.get("source") == "instant"
        indicator = "⚡" if is_instant else "S"
        description = "Instant Lockout" if is_instant else "Scheduled"

        all_rows.append(
            (
                -2,  # Sorts to the very top
                indicator,
                active_lockout.get("start_time", "Now"),
                active_lockout.get("end_time", "..."),
                in_text,
                format_duration_seconds(active_lockout.get("duration_mins", 0) * 60),
                mode,
                blocked_apps_str,
                "No",
                description,
            )
        )

    # 3. Sort and render table
    all_rows.sort(key=lambda x: x[0])

    if not all_rows:
        console.print("[yellow]No scheduled or active lockouts found.[/yellow]")
        return

    table = Table(title="Active & Scheduled Lockouts")
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("Start", style="magenta")
    table.add_column("End", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Duration (m)", style="blue")
    table.add_column("Mode", style="yellow")
    table.add_column("Blocked Apps", style="magenta")
    table.add_column("Persist", style="yellow")
    table.add_column("Description", style="white")

    for row in all_rows:
        table.add_row(*row[1:])

    console.print(table)


@app.command()
def remove(
    index: str = typer.Argument(
        ..., help="Index of the schedule to remove (e.g. 1 or S1)"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Remove a schedule by its index in the list."""
    setup_logging(verbose=verbose)
    sm = ScheduleManager()
    schedules_with_info = sm.check_schedules()

    # Handle S1, S2 style indices
    idx_str = index.upper()
    if idx_str.startswith("S"):
        idx_str = idx_str[1:]
    
    try:
        idx = int(idx_str)
    except ValueError:
        console.print(f"[red]Error:[/red] Invalid index format: {index}")
        raise typer.Exit(1)

    if idx < 1 or idx > len(schedules_with_info):
        console.print(f"[red]Error:[/red] Index {idx} is out of range.")
        raise typer.Exit(1) from None

    target_sched, _, _, _ = schedules_with_info[idx - 1]
    sm.remove_schedule(str(target_sched.id))
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
    apps: list[str] | None = typer.Option(
        None, "--apps", "-a", help="Default apps to block (comma separated)"
    ),
    max_lockout_mins: int | None = typer.Option(
        None, "--max-lockout", "-m", help="Maximum lockout duration in minutes (guardrail)"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Configure notification and app blocking settings."""
    setup_logging(verbose=verbose)
    current_settings = load_settings()

    if lead_mins is not None:
        current_settings.notify_lead_minutes = lead_mins
    if summary is not None:
        current_settings.notify_summary = summary
    if body is not None:
        current_settings.notify_body = body
    if apps:
        current_settings.blocked_apps = process_apps_list(apps)
    if max_lockout_mins is not None:
        if max_lockout_mins < 1:
            console.print("[red]Error:[/red] Maximum lockout duration must be at least 1 minute.")
            raise typer.Exit(1)
        console.print(
            "\n[bold red]WARNING:[/bold red] Changing the maximum lockout duration "
            "can lead to extended lockouts. Ensure you understand the risks. "
            "Set this value carefully."
        )
        current_settings.MAX_LOCKOUT_MINUTES = max_lockout_mins

    current_settings.save()

    table = Table(title="Current Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="magenta")
    table.add_row("Lead Minutes", str(current_settings.notify_lead_minutes))
    table.add_row("Summary Template", current_settings.notify_summary)
    table.add_row("Body Template", current_settings.notify_body)
    table.add_row("Default Blocked Apps", ", ".join(current_settings.blocked_apps))
    table.add_row("Max Lockout Duration (m)", str(current_settings.MAX_LOCKOUT_MINUTES))
    console.print(table)
    console.print("[green]Configuration saved![/green]")

@app.command()
def status(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Check the status of the daemon and active lockouts."""
    import json

    setup_logging(verbose=verbose)

    # 1. Systemd Service Status
    is_active = False
    systemd_pid = None
    try:
        active_res = subprocess.run(
            ["systemctl", "--user", "is-active", "lmout.service"],
            capture_output=True,
            text=True,
        )
        is_active = active_res.stdout.strip() == "active"

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

            if daemon_pid:
                try:
                    os.kill(daemon_pid, 0)
                except OSError:
                    daemon_pid = None
        except Exception:
            pass

    if not daemon_pid and systemd_pid:
        daemon_pid = systemd_pid

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
        mode = (
            "App Blocking Only" if active_lockout.get("block_only") else "Full Lockout"
        )
        console.print(f"\n[bold yellow]⚠️ ACTIVE SESSION ({mode})[/bold yellow]")
        console.print(f"Duration: {active_lockout.get('duration_mins')}m")
        console.print(f"Started at: {active_lockout.get('start_time')}")
        apps = active_lockout.get("blocked_apps")
        if apps:
            console.print(f"Blocking: [magenta]{', '.join(apps)}[/magenta]")
    else:
        console.print("\nNo lockout currently active.")

    if not is_active and not daemon_pid:
        console.print(
            "\n[dim]To start the daemon, run: [bold]lmout start[/bold] or use systemd.[/dim]"
        )


@app.command()
def start(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    daemonize: bool = typer.Option(
        False,
        "--daemonize",
        hidden=True,
        help="Internal flag for systemd to run the daemon directly.",
    ),
) -> None:
    """Starts and manages the lockout daemon using systemd."""
    setup_logging(verbose=verbose)

    if daemonize:
        # This is the execution path for systemd. It runs the daemon in the
        # foreground from systemd's perspective.
        from lock_me_out.daemon import run_daemon

        console.print("Daemon process started directly.")
        run_daemon()
        return

    # --- User-facing 'lmout run' logic ---

    service_file = Path(os.path.expanduser("~/.config/systemd/user/lmout.service"))
    if not service_file.exists():
        console.print(
            "[red]Error:[/red] systemd service file not found. "
            "Please run the `install.sh` script first."
        )
        raise typer.Exit(1)

    if is_daemon_running():
        console.print("[yellow]Daemon is already running.[/yellow]")
        return

    console.print("Daemon is not running. Attempting to start it via systemd...")

    try:
        subprocess.run(
            ["systemctl", "--user", "start", "lmout.service"],
            check=True,
            capture_output=True,
            text=True,
        )

        console.print("Waiting for daemon to initialize...")
        time.sleep(2)

        if is_daemon_running():
            console.print("[bold green]✔ Daemon started successfully via systemd.[/bold green]")
        else:
            console.print(
                "[bold red]✖ Error:[/bold red] Failed to start daemon. Check service "
                "status with `systemctl --user status lmout.service` or logs with "
                "`journalctl --user -u lmout.service`."
            )
    except FileNotFoundError:
        console.print(
            "[red]Error:[/red] `systemctl` command not found. "
            "This command requires a systemd-based OS."
        )
        raise typer.Exit(1)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error starting systemd service:[/red]")
        console.print(f"[dim]{e.stderr}[/dim]")
        raise typer.Exit(1)
