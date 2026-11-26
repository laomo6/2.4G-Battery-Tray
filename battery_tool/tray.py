"""Win32 notification-area thread: two icons, SetTimer, no polling loop."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import queue
import threading
import time

from . import icons
from .protocols import Reading, STATUS_OK

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_APP = 0x8000
WM_TRAY_CALLBACK = WM_APP + 1
WM_TRAY_WAKE = WM_APP + 2
WM_TRAY_SHOW = WM_APP + 3
WM_TIMER = 0x0113
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205

NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
IDC_ARROW = 32512
TIMER_ID = 1

WINDOW_CLASS = "BatteryTrayWndClass"
WINDOW_TITLE = "2.4G电量托盘"


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.DWORD),
        ("hWnd", w.HWND),
        ("uID", w.UINT),
        ("uFlags", w.UINT),
        ("uCallbackMessage", w.UINT),
        ("hIcon", w.HANDLE),
        ("szTip", w.WCHAR * 128),
        ("dwState", w.DWORD),
        ("dwStateMask", w.DWORD),
        ("szInfo", w.WCHAR * 256),
        ("uVersion", w.UINT),
        ("szInfoTitle", w.WCHAR * 64),
        ("dwInfoFlags", w.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", w.HANDLE),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.UINT),
        ("style", w.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", w.HINSTANCE),
        ("hIcon", w.HICON),
        ("hCursor", w.HANDLE),
        ("hbrBackground", w.HBRUSH),
        ("lpszMenuName", w.LPCWSTR),
        ("lpszClassName", w.LPCWSTR),
        ("hIconSm", w.HICON),
    ]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = w.ATOM
user32.CreateWindowExW.argtypes = [
    w.DWORD,
    w.LPCWSTR,
    w.LPCWSTR,
    w.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    w.HWND,
    w.HMENU,
    w.HINSTANCE,
    ctypes.c_void_p,
]
user32.CreateWindowExW.restype = w.HWND
user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DestroyWindow.argtypes = [w.HWND]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.PostMessageW.restype = w.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.SetTimer.argtypes = [w.HWND, ctypes.c_size_t, w.UINT, ctypes.c_void_p]
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = [w.HWND, ctypes.c_size_t]
user32.FindWindowW.argtypes = [w.LPCWSTR, w.LPCWSTR]
user32.FindWindowW.restype = w.HWND
kernel32.GetModuleHandleW.argtypes = [w.LPCWSTR]
kernel32.GetModuleHandleW.restype = w.HMODULE
user32.LoadCursorW.argtypes = [w.HINSTANCE, ctypes.c_void_p]
user32.LoadCursorW.restype = w.HANDLE
user32.RegisterWindowMessageW.argtypes = [w.LPCWSTR]
user32.RegisterWindowMessageW.restype = w.UINT
shell32.Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = w.BOOL


def _tip(reading: Reading) -> str:
    pct = reading.percent
    stamp = time.strftime("%H:%M", time.localtime(reading.ts))
    value = f"{pct}%" if pct is not None else "电量未知"
    return f"{reading.name}：{value}（{stamp}）"[:127]


class Tray:
    def __init__(self, event_queue: queue.Queue, interval: int = 60):
        self.event_queue = event_queue
        self.interval = max(30, min(1800, int(interval)))
        self.thread = threading.Thread(target=self._run, name="BatteryTray", daemon=False)
        self.ready = threading.Event()
        self._cmds: queue.Queue = queue.Queue()
        self._hwnd = None
        self._added = [False, False]
        self._current_icons = [None, None]
        self._last_rows: list[Reading] = []
        self._icon_cache = icons.IconCache()
        self._wndproc = None
        self._taskbar_created = 0
        self._stopping = False

    # -- public API ------------------------------------------------------
    def start(self):
        self.thread.start()
        self.ready.wait(3.0)

    @property
    def hwnd(self):
        return self._hwnd

    def update(self, readings: list[Reading]):
        self._cmds.put(("update", readings))
        self._wake()

    def set_interval(self, seconds: int):
        self.interval = max(30, min(1800, int(seconds)))
        self._cmds.put(("interval", self.interval))
        self._wake()

    def stop(self, timeout: float = 3.0):
        if not self.thread.is_alive():
            return
        self._stopping = True
        self._cmds.put(("quit", None))
        self._wake()
        self.thread.join(timeout)

    def _wake(self):
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_TRAY_WAKE, 0, 0)

    # -- window thread ---------------------------------------------------
    def _run(self):
        try:
            self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
            hinst = kernel32.GetModuleHandleW(None)
            self._wndproc = WNDPROC(self._wndproc_impl)
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.style = 0
            wc.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p)
            wc.hInstance = hinst
            wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
            wc.lpszClassName = WINDOW_CLASS
            atom = user32.RegisterClassExW(ctypes.byref(wc))
            if not atom and ctypes.get_last_error() != 1410:  # ERROR_CLASS_ALREADY_EXISTS
                self.event_queue.put(("tray_error", f"RegisterClassExW failed: {ctypes.get_last_error()}"))
                return
            # A hidden top-level window is needed for the TaskbarCreated broadcast.
            self._hwnd = user32.CreateWindowExW(
                0, WINDOW_CLASS, WINDOW_TITLE, 0, 0, 0, 0, 0, None, None, hinst, None
            )
            if not self._hwnd:
                self.event_queue.put(("tray_error", f"CreateWindowExW failed: {ctypes.get_last_error()}"))
                return
            self._add_initial()
            user32.SetTimer(self._hwnd, TIMER_ID, self.interval * 1000, None)
            self.ready.set()
            msg = w.MSG()
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == -1 or ret == 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self.event_queue.put(("tray_error", f"{type(exc).__name__}: {exc}"))
        finally:
            self._hwnd = None
            self.ready.set()
            self._remove_all()
            self._icon_cache.clear()

    def _add_initial(self):
        gray = Reading("mouse", "鼠标", "鼠标", status="missing")
        self._last_rows = [gray, Reading("secondary", "键盘", "键盘", status="missing")]
        self._refresh_icons(add=True)

    def _wndproc_impl(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY_CALLBACK:
                code = int(lparam) & 0xFFFF
                if code in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self.event_queue.put(("refresh", "tray-left"))
                elif code == WM_RBUTTONUP:
                    self.event_queue.put(("show_panel", "tray-right"))
                return 0
            if msg == WM_TIMER:
                self.event_queue.put(("refresh", "timer"))
                return 0
            if msg == WM_TRAY_WAKE:
                self._drain_commands()
                return 0
            if msg == WM_TRAY_SHOW:
                self.event_queue.put(("show_panel", "single-instance"))
                return 0
            if self._taskbar_created and msg == self._taskbar_created:
                self._remove_all()
                self._added = [False, False]
                self._refresh_icons(add=True)
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                self._remove_all()
                user32.KillTimer(hwnd, TIMER_ID)
                user32.PostQuitMessage(0)
                self.event_queue.put(("tray_closed", None))
                return 0
        except Exception as exc:
            self.event_queue.put(("tray_error", f"WndProc: {type(exc).__name__}: {exc}"))
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _drain_commands(self):
        while True:
            try:
                cmd, payload = self._cmds.get_nowait()
            except queue.Empty:
                break
            if cmd == "update":
                self._last_rows = list(payload)
                self._refresh_icons(add=False)
            elif cmd == "interval":
                if self._hwnd:
                    user32.KillTimer(self._hwnd, TIMER_ID)
                    user32.SetTimer(self._hwnd, TIMER_ID, int(payload) * 1000, None)
            elif cmd == "quit":
                if self._hwnd:
                    user32.DestroyWindow(self._hwnd)
                return
            elif cmd == "readd":
                self._added = [False, False]
                self._refresh_icons(add=True)

    def _refresh_icons(self, add: bool):
        if not self._hwnd:
            return
        rows = list(self._last_rows)
        while len(rows) < 2:
            rows.append(Reading("secondary", "键盘", "设备", status="missing"))
        for i in range(2):
            reading = rows[i]
            gray = reading.status != STATUS_OK or reading.stale
            icon = self._icon_cache.get(reading.percent, reading.charging, gray)
            if not icon:
                continue
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = self._hwnd
            nid.uID = i + 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_TRAY_CALLBACK
            nid.hIcon = icon
            nid.szTip = _tip(reading)
            ok = False
            if self._added[i] and not add:
                ok = shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
            if not ok:
                ok = shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
                if ok:
                    self._added[i] = True
            if ok:
                # Icons are owned by IconCache; do not destroy them here.
                self._current_icons[i] = icon

    def _remove_all(self):
        if not self._hwnd:
            return
        for i in range(2):
            if self._added[i]:
                nid = NOTIFYICONDATAW()
                nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
                nid.hWnd = self._hwnd
                nid.uID = i + 1
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                self._added[i] = False
            self._current_icons[i] = None


def signal_existing() -> bool:
    hwnd = user32.FindWindowW(WINDOW_CLASS, WINDOW_TITLE)
    if hwnd:
        user32.PostMessageW(hwnd, WM_TRAY_SHOW, 0, 0)
        return True
    return False


def find_tray_window():
    return user32.FindWindowW(WINDOW_CLASS, WINDOW_TITLE)
