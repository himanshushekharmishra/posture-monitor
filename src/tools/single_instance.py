"""Make sure only one background monitor runs at a time.

Two copies would fight over the camera and show two tray icons. On Windows a named
mutex does this reliably: the OS removes it when the process exits, even after a
crash, so there's no stale lock file to clean up.
"""
from __future__ import annotations

import sys

ERROR_ALREADY_EXISTS = 183
_held: list[object] = []  # keep handles alive for the life of the process


def acquire(name: str = "PostureMonitor") -> bool:
    """True if this process is now the only instance; False if one is already running.
    Always True on non-Windows systems (the app targets Windows)."""
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    handle = kernel32.CreateMutexW(None, False, f"Local\\{name}")
    if not handle:
        return True  # couldn't create it; don't block the user from running the app
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _held.append(handle)
    return True
