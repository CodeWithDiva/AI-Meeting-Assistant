"""Tell the user when the machine is too short on RAM for accurate transcription.

Measured on the development machine: 654 MB free out of 16 GB, with Ollama's
loaded 7B model alone holding 5.2 GB and dozens of browser tabs holding the
rest. Whisper then failed to load its Urdu model (`mkl_malloc: failed to
allocate memory`) and fell back to the far weaker `base`.

An earlier version of this module unloaded Ollama's model to make room. That
made things worse: with the browsers still open the 7B model could not be
loaded *again* (`unable to allocate CPU_REPACK buffer of size 3.1 GB`), so every
answer and the meeting's notes fell back to the offline canned path. Nothing
here touches the language model any more — it only measures, and says so.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Below this much free RAM, the accurate Urdu model may not load.
MIN_FREE_RAM_MB = int(os.getenv("BOT_MIN_FREE_RAM_MB", "2500"))


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def free_ram_mb() -> int | None:
    """Free physical RAM in MB, or None where it can't be read."""
    if sys.platform != "win32":
        try:
            with open("/proc/meminfo", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) // 1024
        except OSError:
            return None
        return None
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
        return None
    return int(status.ullAvailPhys // (1024 * 1024))


def low_memory_warning() -> str | None:
    """A message for the user if RAM is short right now, else None. Never raises."""
    try:
        free = free_ram_mb()
    except Exception:
        return None
    if free is None or free >= MIN_FREE_RAM_MB:
        return None
    return (
        f"Only {free} MB of RAM is free on this PC. Live transcription may use a "
        "smaller, less accurate model (Urdu suffers most) until memory frees up — "
        "close browser tabs (Chrome/Edge) or other heavy apps for accurate results."
    )
