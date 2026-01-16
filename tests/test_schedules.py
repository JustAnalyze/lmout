import pytest
import json
from pathlib import Path
from uuid import UUID
from lock_me_out.manager import ScheduleManager
from lock_me_out.schema import LockSchedule
from lock_me_out.settings import settings


def test_schedule_manager_persistence(tmp_path):
    # Setup tmp data dir
    original_data_dir = settings.data_dir
    settings.data_dir = tmp_path

    manager = ScheduleManager()
    manager.add_schedule("8pm", "9pm", "Test Sched")

    assert len(manager.schedules) == 1
    assert manager.schedules[0].start_time == "8pm"

    # Reload manager
    manager2 = ScheduleManager()
    assert len(manager2.schedules) == 1
    assert manager2.schedules[0].start_time == "8pm"
    assert isinstance(manager2.schedules[0].id, UUID)

    # Cleanup
    settings.data_dir = original_data_dir


def test_schedule_manager_remove(tmp_path):
    original_data_dir = settings.data_dir
    settings.data_dir = tmp_path

    manager = ScheduleManager()
    s = manager.add_schedule("8pm", "9pm")
    manager.remove_schedule(s.id)

    assert len(manager.schedules) == 0

    settings.data_dir = original_data_dir
