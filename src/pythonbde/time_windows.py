"""Persistent weekly time windows; 15-minute increments, no Qt dependency.

An empty slot is unassigned (shown in the fourth, read-only grid row).
Only one of Work-Time, Maintaine-Time and Free-Time can own a slot.
This describes scheduling policy; it does NOT yet enforce logins or disconnects.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

SLOT_MINUTES = 15
SLOTS_PER_DAY = 24 * 60 // SLOT_MINUTES
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
TYPES = ("Work-Time", "Maintaine-Time", "Free-Time")
UNASSIGNED = ""


def empty_schedule():
    return {day: [UNASSIGNED] * SLOTS_PER_DAY for day in DAYS}


def slot_label(index: int) -> str:
    if not 0 <= index < SLOTS_PER_DAY:
        raise ValueError("Time-slot index must be between 0 and 95")
    start = index * SLOT_MINUTES
    end = start + SLOT_MINUTES
    return f"{start // 60:02d}:{start % 60:02d}–{end // 60:02d}:{end % 60:02d}"


def validate_schedule(days):
    if not isinstance(days, dict) or set(days) != set(DAYS):
        raise ValueError("Time Window schedule must contain seven weekdays")
    for day, row in days.items():
        if not isinstance(row, list) or len(row) != SLOTS_PER_DAY:
            raise ValueError(f"Invalid number of time slots for {day}")
        if any(type(value) is not str or value not in (*TYPES, UNASSIGNED) for value in row):
            raise ValueError(f"Invalid time window category for {day}")
    return days


def load_schedule(filename):
    path = Path(filename)
    if not path.exists():
        return empty_schedule()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or data.get("slot_minutes") != SLOT_MINUTES:
        raise ValueError("Unsupported time window file version or interval")
    return validate_schedule(data.get("days"))


def save_schedule(filename, days):
    """Write atomically; do not leave truncated data if interrupted."""
    validate_schedule(days)
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".time-window-", suffix=".tmp", dir=str(path.parent))
    try:
        if os.name == 'posix':
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "slot_minutes": SLOT_MINUTES, "days": days}, handle,
                      ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def set_slot(days, day, index, category):
    validate_schedule(days)
    if day not in DAYS or not 0 <= index < SLOTS_PER_DAY or category not in (*TYPES, UNASSIGNED):
        raise ValueError("Invalid time window selection")
    days[day][index] = category


def time_window_path(dbf_path):
    return Path(dbf_path).resolve().parent / 'time_windows.json'
