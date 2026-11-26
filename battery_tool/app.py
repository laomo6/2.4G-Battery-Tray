"""Application orchestrator: Tk main thread + Win32 tray thread + worker."""
from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from . import install
from .config import Config
from .debug_ui import DebugWindow
from .devices import DeviceManager
from .tray import Tray
from .ui import Panel


class App:
    def __init__(self, *, tray_mode: bool = True, show_panel: bool = True, debug: bool = False, interval: int | None = None):
        self.config = Config()
        if interval is not None:
            self.config.set_interval(interval)
        self.debug = debug
        self.manager = DeviceManager(self.config)
        self.root = tk.Tk()
        self.root.title("2.4G 电量")
        self.queue: queue.Queue = queue.Queue()
        self._quitting = False
        self._worker: threading.Thread | None = None
        self._pending = False
        self._panel_timer = None
        self._debug_window: DebugWindow | None = None

        self.panel = Panel(
            self.root,
            on_refresh=lambda: self.request_refresh("button"),
            on_interval=self.on_interval,
            on_autostart=self.on_autostart,
            on_debug=self.open_debug,
            on_close=self.on_panel_close,
            on_exit=self.quit_app,
            interval=self.config.interval,
            autostart=install.autostart_enabled(),
        )
        self.tray: Tray | None = None
        if tray_mode:
            self.tray = Tray(self.queue, self.config.interval)
            try:
                self.tray.start()
                if not self.tray.hwnd:
                    messagebox.showwarning("托盘不可用", "通知区域图标创建失败，将继续使用面板。")
                    self.tray = None
            except Exception as exc:
                messagebox.showwarning("托盘不可用", f"{type(exc).__name__}: {exc}")
                self.tray = None

        if not show_panel:
            self.panel.hide()
        if debug:
            self.open_debug()
        self.root.after(250, lambda: self.request_refresh("startup"))
        self.root.after(150, self._pump)

    # -- refresh ---------------------------------------------------------
    def request_refresh(self, source: str = "manual"):
        if self._quitting:
            return
        if self._worker is not None and self._worker.is_alive():
            self._pending = True
            return
        self._worker = threading.Thread(target=self._read_worker, name="BatteryRead", daemon=True)
        self._worker.start()

    def _read_worker(self):
        try:
            rows = self.manager.read_all()
            self.queue.put(("readings", rows))
        except Exception as exc:
            self.queue.put(("error", f"{type(exc).__name__}: {exc}"))
        finally:
            self.queue.put(("refresh_done", None))

    def _on_readings(self, rows):
        self.panel.update_readings(rows)
        if self.debug:
            for r in rows:
                print(
                    f"[debug] {r.slot}: {r.name} pct={r.percent} status={r.status} "
                    f"stale={r.stale} source={r.source} detail={r.detail}",
                    flush=True,
                )
        if self.tray is not None:
            self.tray.update(rows)
        else:
            self._schedule_panel_refresh()

    def _schedule_panel_refresh(self):
        if self._quitting or self.tray is not None:
            return
        if self._panel_timer is not None:
            try:
                self.root.after_cancel(self._panel_timer)
            except Exception:
                pass
        self._panel_timer = self.root.after(self.config.interval * 1000, lambda: self.request_refresh("panel-timer"))

    # -- queue pump ------------------------------------------------------
    def _pump(self):
        if self._quitting:
            return
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "refresh":
                    self.request_refresh(payload or "event")
                elif kind == "show_panel":
                    self.show_panel()
                elif kind == "readings":
                    self._on_readings(payload)
                elif kind == "refresh_done":
                    if self._pending:
                        self._pending = False
                        self.request_refresh("pending")
                elif kind == "error":
                    self.panel.set_status("读取失败：" + str(payload))
                elif kind == "tray_closed":
                    if not self._quitting:
                        self.quit_app()
                elif kind == "tray_error":
                    if not self._quitting:
                        messagebox.showerror("托盘错误", str(payload))
                        self.quit_app()
        except queue.Empty:
            pass
        except Exception as exc:
            try:
                self.panel.set_status(f"内部错误：{exc}")
            except Exception:
                pass
        try:
            self.root.after(150, self._pump)
        except tk.TclError:
            pass

    # -- panel / tray ----------------------------------------------------
    def show_panel(self):
        try:
            self.panel.set_autostart(install.autostart_enabled())
        except Exception:
            pass
        self.panel.show()

    def on_panel_close(self):
        if self.tray is not None:
            self.panel.hide()
        else:
            self.quit_app()

    def on_interval(self, seconds: int):
        self.config.set_interval(seconds)
        self.panel.set_interval(seconds)
        if self.tray is not None:
            self.tray.set_interval(seconds)
        else:
            self._schedule_panel_refresh()

    def on_autostart(self, enabled: bool):
        try:
            if enabled:
                ok, msg = install.install_autostart()
            else:
                ok, msg = install.remove_autostart()
        except Exception as exc:
            ok, msg = False, f"{type(exc).__name__}: {exc}"
        actual = install.autostart_enabled()
        self.panel.set_autostart(actual)
        if not ok:
            messagebox.showwarning("开机自启", msg)
        self.panel.set_status(msg)
        if self.tray is not None:
            self.tray.set_interval(self.config.interval)

    # -- debug -----------------------------------------------------------
    def open_debug(self):
        if self._debug_window is not None:
            try:
                self._debug_window.deiconify()
                self._debug_window.lift()
                return
            except Exception:
                self._debug_window = None
        self._debug_window = DebugWindow(self.root, self.config, self.manager)

    # -- lifecycle -------------------------------------------------------
    def quit_app(self):
        if self._quitting:
            return
        self._quitting = True
        if self._panel_timer is not None:
            try:
                self.root.after_cancel(self._panel_timer)
            except Exception:
                pass
        if self.tray is not None:
            try:
                self.tray.stop(3.0)
            except Exception:
                pass
            self.tray = None
        if self._debug_window is not None:
            try:
                self._debug_window.destroy()
            except Exception:
                pass
            self._debug_window = None
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        try:
            self.root.mainloop()
        finally:
            if not self._quitting:
                self.quit_app()
