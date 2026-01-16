import os
import subprocess
import time

import typer
from rich.console import Console
from rich.table import Table

from lock_me_out.utils.logging import setup_logging
from lock_me_out.manager import LockOutManager, ScheduleManager
from lock_me_out.settings import load_settings, settings
from lock_me_out.utils.time import calculate_from_range

app = typer.Typer(help="Lock Me Out - CLI Schedule Manager")
console = Console()


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
        calculate_from_range(start_time, end_time)
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


@app.command()
def start(
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
    """Start an instant lockout session."""
    setup_logging(verbose=verbose)
    processed_apps = process_apps_list(apps)
    blocked_apps = processed_apps if processed_apps else settings.blocked_apps

    manager = LockOutManager(delay * 60, duration * 60)
    mode_text = "App Blocking" if block_only else "Full Lockout"
    console.print(
        f"[bold green]Starting instant {mode_text}...[/bold green] "
        f"Delay: {delay}m, Duration: {duration}m"
    )
    if blocked_apps:
        console.print(f"Blocking apps: [magenta]{', '.join(blocked_apps)}[/magenta]")

    manager.start(blocked_apps=blocked_apps, block_only=block_only)

    try:
        while manager.get_status()["state"] != "IDLE":
            time.sleep(1)
    except KeyboardInterrupt:
        manager.stop()
        console.print("\n[yellow]Lockout stopped manually.[/yellow]")


@app.command(name="list")
def list_schedules(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """List all scheduled lockouts, sorted by soonest first."""
    setup_logging(verbose=verbose)
    sm = ScheduleManager()
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
    table.add_column("Mode", style="yellow")
    table.add_column("Blocked Apps", style="magenta")
    table.add_column("Persist", style="yellow")
    table.add_column("Description", style="white")

    for i, (sched, delay_secs, duration_secs) in enumerate(schedules_with_info, 1):
        if delay_secs == 0:
            in_text = "NOW"
        elif delay_secs < 60:
            in_text = f"{delay_secs}s"
        elif delay_secs < 3600:
            in_text = f"{delay_secs // 60}m"
        else:
            in_text = f"{delay_secs // 3600}h {(delay_secs % 3600) // 60}m"

        mode = "Apps Only" if sched.block_only else "Full Lock"
        blocked_apps = ", ".join(sched.blocked_apps) if sched.blocked_apps else "None"

        table.add_row(
            str(i),
            sched.start_time,
            sched.end_time,
            in_text,
            str(duration_secs // 60),
            mode,
            blocked_apps,
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
    """Remove a schedule by its index in the list."""
    setup_logging(verbose=verbose)
    sm = ScheduleManager()
    schedules_with_info = sm.check_schedules()

    if index < 1 or index > len(schedules_with_info):
        console.print(f"[red]Error:[/red] Index {index} is out of range.")
        raise typer.Exit(1) from None

    target_sched, _, _ = schedules_with_info[index - 1]
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

    current_settings.save()

    table = Table(title="Current Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="magenta")
    table.add_row("Lead Minutes", str(current_settings.notify_lead_minutes))
    table.add_row("Summary Template", current_settings.notify_summary)
    table.add_row("Body Template", current_settings.notify_body)
    table.add_row("Default Blocked Apps", ", ".join(current_settings.blocked_apps))
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
            "\n[dim]To start the daemon, run: [bold]lmout run[/bold] or use systemd.[/dim]"
        )


@app.command()
def run(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Run the lockout daemon to enforce schedules."""
    from lock_me_out.daemon import run_daemon

    setup_logging(verbose=verbose)
    run_daemon()
