# Lock Me Out (lmout)

> "Vibe-coded to force me to touch grass because I lack self-control."

Lock Me Out is a robust CLI tool designed for Linux users who need a little help stepping away from the screen. Whether you're in the zone or just can't seem to close that last tab, `lmout` ensures you take the breaks you need by enforcing scheduled lockouts or blocking specific distracting applications.

## ✨ Features

- **Scheduled Lockouts**: Plan your breaks in advance (e.g., `8pm` to `8:30pm`).
- **Instant Lockout**: Need an immediate break? Start a session with a custom delay and duration.
- **App Blocking**: Don't want a full lockout? Specify a list of apps to kill during your session.
- **Persistent Schedules**: Mark schedules as persistent to have them repeat every day.
- **Desktop Notifications**: Get warned before a lockout starts so you can save your work.
- **Daemon Mode**: Runs as a background service (supports systemd) to enforce your schedules.

## 🚀 Installation

### Using the Install Script (Recommended)

The easiest way to install `lmout` and set up the background daemon is using the provided script:

```bash
git clone https://github.com/JustAnalyze/lmout.git
cd lmout
./install.sh
```

### Manual Installation

If you prefer to do it manually:

1. **Install the package**:
   ```bash
   uv tool install .
   ```

2. **Set up the systemd service**:
   Copy `lmout.service` to `~/.config/systemd/user/` and enable it:
   ```bash
   systemctl --user enable --now lmout.service
   ```

## 🛠 Usage

### Adding a Schedule
```bash
# Add a full lockout from 8 PM to 9 PM
lmout add 8pm 9pm --desc "Evening relaxation"

# Add an app-blocking-only session (non-intrusive)
lmout add 10:30pm 11pm --apps "chrome,code" --block-only --persist
```

### Starting the Daemon & Instant Lockouts
```bash
# Start the daemon in the background via systemd
lmout start

# Start a 10-minute lockout after a 30-minute delay
lmout instant --delay 30 --duration 10
```

### Checking Status & Listing
```bash
# See all scheduled lockouts and any active instant/scheduled lockouts
lmout list

# Check if the daemon and active sessions are running
lmout status
```

### Configuration
```bash
# Customize notification lead time and default apps to block
lmout config --lead 10 --apps "nvim,antigravity"
```

## 🤝 Contributing

This project is built to be modular and easy to understand. Contributions are welcome!
- **`schema.py`**: Pydantic models for data validation, configuration, and API schemas.
- **`manager.py`**: Business logic for managing sessions and persistence.
- **`daemon.py`**: The background loop logic.
- **`cli.py`**: Typer commands and user interface.
- **`utils/`**: Helper modules for time, notifications, and process management.

---
Made with ❤️ by a developer who needed to touch some grass.
