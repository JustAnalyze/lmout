import json
import os
from datetime import datetime

from lock_me_out.settings import settings


def write_state(active_info=None):
    """Writes the current daemon state to a file for 'status' command."""
    state = {
        "pid": os.getpid(),
        "last_update": datetime.now().isoformat(),
        "active_lockout": active_info,
    }
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with open(settings.state_file, "w") as f:
            json.dump(state, f, indent=4)
    except Exception:
        pass


def cleanup_state():
    """Removes the state file when the daemon stops."""
    if settings.state_file.exists():
        try:
            settings.state_file.unlink()
        except Exception:
            pass
