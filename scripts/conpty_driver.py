"""scripts/conpty_driver.py — Native Windows ConPTY Interactive Driver for Claude Code.

Provides a robust pseudo-terminal (ConPTY) environment for interactive CLI sessions,
supporting keystroke injection, screen scraping, ANSI escape sequence handling,
state-based condition waits, virtual terminal screen snapshots, and guaranteed
process-tree cleanup.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import re
import subprocess
import sys
import threading
import time
from typing import Callable, Optional, Pattern

# ---------------------------------------------------------------------------
# Win32 ConPTY Definitions
# ---------------------------------------------------------------------------
kernel32 = ctypes.windll.kernel32

COORD = wintypes._COORD
HPCON = wintypes.HANDLE

PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
STARTF_USESTDHANDLES = 0x00000100
CREATE_UNICODE_ENVIRONMENT = 0x00000400

CreatePseudoConsole = kernel32.CreatePseudoConsole
CreatePseudoConsole.argtypes = [
    COORD,
    wintypes.HANDLE,
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.POINTER(HPCON),
]
CreatePseudoConsole.restype = ctypes.HRESULT

ClosePseudoConsole = kernel32.ClosePseudoConsole
ClosePseudoConsole.argtypes = [HPCON]
ClosePseudoConsole.restype = None

InitializeProcThreadAttributeList = kernel32.InitializeProcThreadAttributeList
InitializeProcThreadAttributeList.argtypes = [
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(ctypes.c_size_t),
]
InitializeProcThreadAttributeList.restype = wintypes.BOOL

UpdateProcThreadAttribute = kernel32.UpdateProcThreadAttribute
UpdateProcThreadAttribute.argtypes = [
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
    ctypes.c_size_t,
    wintypes.LPVOID,
    ctypes.POINTER(ctypes.c_size_t),
]
UpdateProcThreadAttribute.restype = wintypes.BOOL

DeleteProcThreadAttributeList = kernel32.DeleteProcThreadAttributeList
DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
DeleteProcThreadAttributeList.restype = None


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", STARTUPINFOW),
        ("lpAttributeList", wintypes.LPVOID),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


kernel32.CreateProcessW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.BOOL,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.LPCWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
kernel32.CreateProcessW.restype = wintypes.BOOL

# ANSI escape sequence patterns
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\([a-zA-Z]|\x1b[=>]")
_ANSI_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(\x07|\x1b\\)")


def strip_ansi(text: str) -> str:
    """Removes ANSI CSI and OSC escape sequences from terminal text."""
    clean = _ANSI_CSI_RE.sub("", text)
    clean = _ANSI_OSC_RE.sub("", clean)
    clean = clean.replace("\r\n", "\n").replace("\r", "\n")
    return clean


class VirtualTerminal:
    """A lightweight 2D terminal grid for rendering clean VT snapshots."""

    def __init__(self, cols: int = 120, rows: int = 35):
        self.cols = cols
        self.rows = rows
        self.grid = [[" "] * cols for _ in range(rows)]
        self.cursor_row = 0
        self.cursor_col = 0

    def feed(self, text: str) -> None:
        """Processes text and VT100/ANSI escape codes into the grid."""
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == "\r":
                self.cursor_col = 0
                i += 1
            elif ch == "\n":
                self.cursor_row = min(self.rows - 1, self.cursor_row + 1)
                i += 1
            elif ch == "\b":
                self.cursor_col = max(0, self.cursor_col - 1)
                i += 1
            elif ch == "\t":
                # Tab moves to next 8-char tab stop
                self.cursor_col = min(self.cols - 1, (self.cursor_col // 8 + 1) * 8)
                i += 1
            elif ch == "\x1b":
                if i + 1 < n and text[i + 1] == "[":
                    # CSI sequence
                    m = re.match(r"^\x1b\[([0-9;?]*)([a-zA-Z])", text[i:])
                    if m:
                        i += len(m.group(0))
                        params = m.group(1)
                        cmd = m.group(2)
                        self._handle_csi(cmd, params)
                        continue
                elif i + 1 < n and text[i + 1] == "]":
                    # OSC sequence: \x1b] ... \x07 or \x1b\\
                    m = re.match(r"^\x1b\][^\x07\x1b]*(\x07|\x1b\\)", text[i:])
                    if m:
                        i += len(m.group(0))
                        continue
                elif i + 1 < n and text[i + 1] in "()":
                    # Character set selection, e.g. \x1b(B
                    i += 3
                    continue
                elif i + 1 < n and text[i + 1] in "=>":
                    # Alternate keypad mode
                    i += 2
                    continue
                i += 1
            elif ord(ch) < 32:
                # Other non-printable control characters
                i += 1
            else:
                if 0 <= self.cursor_row < self.rows and 0 <= self.cursor_col < self.cols:
                    self.grid[self.cursor_row][self.cursor_col] = ch
                    self.cursor_col += 1
                    if self.cursor_col >= self.cols:
                        self.cursor_col = 0
                        self.cursor_row = min(self.rows - 1, self.cursor_row + 1)
                i += 1

    def _handle_csi(self, cmd: str, params: str) -> None:
        parts = [int(p) for p in params.split(";") if p.isdigit()]
        if cmd in ("H", "f"):  # Cursor Position (1-indexed)
            r = parts[0] - 1 if len(parts) > 0 and parts[0] > 0 else 0
            c = parts[1] - 1 if len(parts) > 1 and parts[1] > 0 else 0
            self.cursor_row = max(0, min(self.rows - 1, r))
            self.cursor_col = max(0, min(self.cols - 1, c))
        elif cmd == "J":  # Erase in Display
            p = parts[0] if parts else 0
            if p == 2 or p == 3:  # Clear entire screen
                self.grid = [[" "] * self.cols for _ in range(self.rows)]
                self.cursor_row = 0
                self.cursor_col = 0
            elif p == 0:  # Clear from cursor to end
                for c in range(self.cursor_col, self.cols):
                    self.grid[self.cursor_row][c] = " "
                for r in range(self.cursor_row + 1, self.rows):
                    self.grid[r] = [" "] * self.cols
            elif p == 1:  # Clear from start to cursor
                for r in range(0, self.cursor_row):
                    self.grid[r] = [" "] * self.cols
                for c in range(0, self.cursor_col + 1):
                    self.grid[self.cursor_row][c] = " "
        elif cmd == "K":  # Erase in Line
            p = parts[0] if parts else 0
            if p == 0:  # Clear to end of line
                for c in range(self.cursor_col, self.cols):
                    self.grid[self.cursor_row][c] = " "
            elif p == 1:  # Clear to start of line
                for c in range(0, self.cursor_col + 1):
                    self.grid[self.cursor_row][c] = " "
            elif p == 2:  # Clear whole line
                self.grid[self.cursor_row] = [" "] * self.cols
        elif cmd == "A":  # Cursor Up
            n = parts[0] if parts else 1
            self.cursor_row = max(0, self.cursor_row - n)
        elif cmd == "B":  # Cursor Down
            n = parts[0] if parts else 1
            self.cursor_row = min(self.rows - 1, self.cursor_row + n)
        elif cmd == "C":  # Cursor Forward
            n = parts[0] if parts else 1
            self.cursor_col = min(self.cols - 1, self.cursor_col + n)
        elif cmd == "D":  # Cursor Backward
            n = parts[0] if parts else 1
            self.cursor_col = max(0, self.cursor_col - n)
        elif cmd == "G":  # Cursor Horizontal Absolute
            col = parts[0] - 1 if parts and parts[0] > 0 else 0
            self.cursor_col = max(0, min(self.cols - 1, col))
        elif cmd == "d":  # Line Position Absolute
            row = parts[0] - 1 if parts and parts[0] > 0 else 0
            self.cursor_row = max(0, min(self.rows - 1, row))

    def render(self) -> str:
        """Renders the current screen grid as a clean multi-line string."""
        # Replace box-drawing horizontal lines with spaces so embedded labels don't get joined
        lines = [
            "".join(row).replace("\u2500", " ").replace("\u2501", " ").rstrip()
            for row in self.grid
        ]
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)


# Key sequence mappings
SPECIAL_KEYS: dict[str, str] = {
    "ENTER": "\r",
    "RETURN": "\r",
    "ESCAPE": "\x1b",
    "ESC": "\x1b",
    "TAB": "\t",
    "SPACE": " ",
    "BACKSPACE": "\x08",
    "UP": "\x1b[A",
    "DOWN": "\x1b[B",
    "RIGHT": "\x1b[C",
    "LEFT": "\x1b[D",
    "HOME": "\x1b[H",
    "END": "\x1b[F",
    "CTRL_C": "\x03",
    "CTRL_D": "\x04",
    "CTRL_Z": "\x1a",
    "SHIFT_TAB": "\x1b[Z",
}


class ConPTYSession:
    """Manages an interactive process running inside a native Windows PseudoConsole."""

    def __init__(
        self,
        command_line: str,
        cwd: str,
        env: Optional[dict[str, str]] = None,
        cols: int = 120,
        rows: int = 35,
    ):
        self.command_line = command_line
        self.cwd = cwd
        self.env = env or dict(os.environ)
        self.cols = cols
        self.rows = rows

        self.h_in_read = wintypes.HANDLE()
        self.h_in_write = wintypes.HANDLE()
        self.h_out_read = wintypes.HANDLE()
        self.h_out_write = wintypes.HANDLE()
        self.h_pc = HPCON()

        self.proc_info = PROCESS_INFORMATION()
        self.pi_valid = False
        self._attr_list_mem = None

        self._buffer: list[str] = []
        self._raw_bytes = bytearray()
        self._lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self._closed = False
        self._vt = VirtualTerminal(cols=cols, rows=rows)

        self._spawn()

    def _spawn(self) -> None:
        # 1. Create Pipes
        kernel32.CreatePipe(ctypes.byref(self.h_in_read), ctypes.byref(self.h_in_write), None, 0)
        kernel32.CreatePipe(ctypes.byref(self.h_out_read), ctypes.byref(self.h_out_write), None, 0)

        # 2. Create Pseudo Console
        size = COORD(self.cols, self.rows)
        hr = CreatePseudoConsole(size, self.h_in_read, self.h_out_write, 0, ctypes.byref(self.h_pc))
        if hr != 0:
            raise RuntimeError(f"CreatePseudoConsole failed with HRESULT 0x{hr & 0xFFFFFFFF:08x}")

        # 3. Setup attribute list for ConPTY
        size_attr = ctypes.c_size_t(0)
        InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size_attr))

        self._attr_list_mem = ctypes.create_string_buffer(size_attr.value)
        lp_attr = ctypes.cast(self._attr_list_mem, wintypes.LPVOID)
        if not InitializeProcThreadAttributeList(lp_attr, 1, 0, ctypes.byref(size_attr)):
            raise RuntimeError("InitializeProcThreadAttributeList failed")

        if not UpdateProcThreadAttribute(
            lp_attr,
            0,
            PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
            self.h_pc,
            ctypes.sizeof(self.h_pc),
            None,
            None,
        ):
            raise RuntimeError("UpdateProcThreadAttribute failed")

        si_ex = STARTUPINFOEXW()
        si_ex.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        si_ex.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        si_ex.StartupInfo.hStdInput = None
        si_ex.StartupInfo.hStdOutput = None
        si_ex.StartupInfo.hStdError = None
        si_ex.lpAttributeList = lp_attr

        # Format environment block (null-separated, double null-terminated)
        env_str = "".join(f"{k}={v}\0" for k, v in self.env.items()) + "\0"

        # 4. CreateProcessW
        creation_flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT
        cmd = ctypes.create_unicode_buffer(self.command_line)
        cwd = ctypes.create_unicode_buffer(self.cwd)

        res = kernel32.CreateProcessW(
            None,
            cmd,
            None,
            None,
            False,
            creation_flags,
            ctypes.c_wchar_p(env_str),
            cwd,
            ctypes.byref(si_ex.StartupInfo),
            ctypes.byref(self.proc_info),
        )

        # Child pipe ends are owned by ConPTY; close copies in parent
        kernel32.CloseHandle(self.h_in_read)
        self.h_in_read = wintypes.HANDLE()
        kernel32.CloseHandle(self.h_out_write)
        self.h_out_write = wintypes.HANDLE()

        if not res:
            err = kernel32.GetLastError()
            raise RuntimeError(f"CreateProcessW failed with error code {err}")

        self.pi_valid = True

        # 5. Start reader thread
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def _reader_loop(self) -> None:
        buf = ctypes.create_string_buffer(4096)
        bytes_read = wintypes.DWORD()
        while not self._closed:
            success = kernel32.ReadFile(
                self.h_out_read,
                buf,
                ctypes.sizeof(buf),
                ctypes.byref(bytes_read),
                None,
            )
            if not success or bytes_read.value == 0:
                break
            raw = buf.raw[: bytes_read.value]
            with self._lock:
                self._raw_bytes.extend(raw)
                try:
                    text = raw.decode("utf-8", errors="replace")
                except Exception:
                    text = raw.decode("latin-1", errors="replace")
                self._buffer.append(text)
                self._vt.feed(text)
                # When child application (Claude Code) pushes Kitty keyboard enhancement flags (\x1b[>...u),
                # pop them (\x1b[<u) so Claude Code operates in standard VT100/ANSI mode where arrow keys
                # and navigation behave cleanly without duplicate release events.
                if "\x1b[>5u" in text or "\x1b[>1u" in text or "\x1b[>3u" in text:
                    self.write("\x1b[<u")

    def write(self, text: str) -> None:
        """Writes raw text or key sequences into ConPTY input pipe."""
        if self._closed or not self.h_in_write:
            return
        data = text.encode("utf-8")
        bytes_written = wintypes.DWORD()
        kernel32.WriteFile(
            self.h_in_write,
            data,
            len(data),
            ctypes.byref(bytes_written),
            None,
        )

    def send_line(self, text: str = "") -> None:
        """Sends text followed by Enter."""
        self.write(text + "\r")

    def send_key(self, key_name: str) -> None:
        """Sends a named special key, e.g. ENTER, ESC, TAB, UP, DOWN, CTRL_C, SHIFT_TAB."""
        normalized = key_name.strip().upper().replace("-", "_")
        if normalized in SPECIAL_KEYS:
            self.write(SPECIAL_KEYS[normalized])
        else:
            raise ValueError(f"Unknown special key: {key_name}. Available: {list(SPECIAL_KEYS.keys())}")

    def send_enter(self) -> None:
        """Sends Enter key."""
        self.write("\r")

    def send_escape(self) -> None:
        """Sends Escape key."""
        self.write("\x1b")

    def send_ctrl_c(self) -> None:
        """Sends Ctrl+C (ASCII 0x03)."""
        self.write("\x03")

    def send_up(self) -> None:
        """Sends Up arrow key."""
        self.write("\x1b[A")

    def send_down(self) -> None:
        """Sends Down arrow key."""
        self.write("\x1b[B")

    def send_tab(self) -> None:
        """Sends Tab key."""
        self.write("\t")

    def send_space(self) -> None:
        """Sends Space key."""
        self.write(" ")

    def send_shift_tab(self) -> None:
        """Sends Shift+Tab key sequence."""
        self.write("\x1b[Z")

    def paste(self, text: str) -> None:
        """Pastes text using bracketed paste mode if available, or direct UTF-8 injection."""
        # Bracketed paste wraps with \x1b[200~ and \x1b[201~
        self.write(f"\x1b[200~{text}\x1b[201~")

    def get_screen_text(self) -> str:
        """Returns stripped, human-readable terminal output accumulated so far."""
        with self._lock:
            raw = "".join(self._buffer)
        return strip_ansi(raw)

    def get_screen_snapshot(self) -> str:
        """Returns the current 2D rendered terminal screen snapshot."""
        with self._lock:
            return self._vt.render()

    def get_raw_output(self) -> str:
        """Returns raw terminal output including ANSI codes."""
        with self._lock:
            return "".join(self._buffer)

    def save_snapshot(self, file_path: str) -> str:
        """Saves current screen snapshot to a text file and returns the snapshot."""
        snapshot = self.get_screen_snapshot()
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(snapshot)
            f.write("\n")
        return snapshot

    def wait_for(
        self,
        condition: str | Pattern | Callable[[str], bool],
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.05,
        use_snapshot: bool = False,
    ) -> bool:
        """State-based wait for a condition to appear in the terminal buffer.

        No hardcoded sleep: checks the buffer every poll_interval_s up to timeout_s.
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            text = self.get_screen_snapshot() if use_snapshot else self.get_screen_text()
            if callable(condition):
                if condition(text):
                    return True
            elif isinstance(condition, Pattern):
                if condition.search(text):
                    return True
            elif isinstance(condition, str):
                if condition in text:
                    return True

            if not self.is_alive():
                # Check one final time before giving up
                text = self.get_screen_snapshot() if use_snapshot else self.get_screen_text()
                if isinstance(condition, str) and condition in text:
                    return True
                return False

            time.sleep(poll_interval_s)
        return False

    def assert_wait(
        self,
        condition: str | Pattern | Callable[[str], bool],
        timeout_s: float = 30.0,
        message: str = "",
        use_snapshot: bool = False,
    ) -> None:
        """Waits for condition and raises AssertionError if timeout occurs."""
        matched = self.wait_for(condition, timeout_s=timeout_s, use_snapshot=use_snapshot)
        if not matched:
            text = self.get_screen_snapshot() if use_snapshot else self.get_screen_text()
            desc = message or f"Condition {condition!r} not matched within {timeout_s}s"
            raise AssertionError(f"{desc}\nCurrent terminal content:\n{text[-1000:]}")

    def is_alive(self) -> bool:
        """Checks if the child process is still running."""
        if not self.pi_valid or not self.proc_info.hProcess:
            return False
        exit_code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(self.proc_info.hProcess, ctypes.byref(exit_code))
        return exit_code.value == 259  # STILL_ACTIVE

    def get_exit_code(self) -> Optional[int]:
        """Returns process exit code or None if still running."""
        if not self.pi_valid or not self.proc_info.hProcess:
            return None
        exit_code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(self.proc_info.hProcess, ctypes.byref(exit_code))
        if exit_code.value == 259:
            return None
        return int(exit_code.value)

    def close(self, timeout_s: float = 5.0) -> None:
        """Clean shutdown and tree-kill of all child processes."""
        if self._closed:
            return
        self._closed = True

        pid = self.proc_info.dwProcessId if self.pi_valid else 0
        if pid and self.is_alive():
            # Send polite exit first
            try:
                self.send_ctrl_c()
            except Exception:
                pass
            time.sleep(0.2)
            if self.is_alive():
                # Force kill process tree on Windows
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    check=False,
                )

        # Close PseudoConsole to unblock and flush output pipe
        if self.h_pc:
            ClosePseudoConsole(self.h_pc)
            self.h_pc = HPCON()

        # Wait for reader thread to finish reading EOF
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)

        if self.h_in_write:
            kernel32.CloseHandle(self.h_in_write)
            self.h_in_write = wintypes.HANDLE()
        if self.h_out_read:
            kernel32.CloseHandle(self.h_out_read)
            self.h_out_read = wintypes.HANDLE()

        if self._attr_list_mem:
            lp_attr = ctypes.cast(self._attr_list_mem, wintypes.LPVOID)
            DeleteProcThreadAttributeList(lp_attr)
            self._attr_list_mem = None

        if self.pi_valid:
            if self.proc_info.hProcess:
                kernel32.CloseHandle(self.proc_info.hProcess)
            if self.proc_info.hThread:
                kernel32.CloseHandle(self.proc_info.hThread)
            self.pi_valid = False
