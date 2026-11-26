"""Compact dark Tkinter panel with two battery cards."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from .protocols import Reading, STATUS_OK

BG = "#15161a"
CARD = "#202227"
CARD_BORDER = "#2d3037"
FG = "#eceef1"
MUTED = "#8a909b"
FAINT = "#666c76"
GREEN = "#2e9b5c"
YELLOW = "#c69e26"
RED = "#c0392b"
GRAY = "#5b6069"

INTERVAL_CHOICES = [
    ("30 秒", 30),
    ("60 秒", 60),
    ("2 分钟", 120),
    ("5 分钟", 300),
    ("10 分钟", 600),
    ("15 分钟", 900),
    ("30 分钟", 1800),
]


def level_color(percent: int | None, stale: bool = False) -> str:
    if percent is None or stale:
        return GRAY
    if percent >= 60:
        return GREEN
    if percent >= 30:
        return YELLOW
    return RED


def _round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kwargs):
    points = [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class Card(tk.Canvas):
    def __init__(self, master, label: str):
        super().__init__(master, width=278, height=220, bg=BG, highlightthickness=0)
        self.label = label
        self._pct = None
        self._stale = False
        self._draw()

    def _draw(self):
        self.delete("all")
        _round_rect(self, 0, 0, 278, 220, 14, fill=CARD, outline=CARD_BORDER, width=1)
        self._label_id = self.create_text(18, 16, text=self.label, anchor="nw", fill=MUTED, font=("Segoe UI", 10))
        self._pct_id = self.create_text(18, 42, text="--", anchor="nw", fill=GRAY, font=("Segoe UI", 40, "bold"))
        self._pct_suffix = self.create_text(116, 62, text="%", anchor="nw", fill=GRAY, font=("Segoe UI", 17, "bold"))
        self._status_id = self.create_text(258, 20, text="读取中", anchor="ne", fill=FAINT, font=("Segoe UI", 9))
        self._name_id = self.create_text(18, 104, text="", anchor="nw", fill=FG, font=("Segoe UI", 10, "bold"))
        self._bar_bg = _round_rect(self, 18, 128, 260, 138, 5, fill="#30343b", outline="")
        self._bar_fill = _round_rect(self, 18, 128, 18, 138, 5, fill=GRAY, outline="")
        self._source_id = self.create_text(18, 146, text="", anchor="nw", fill=FAINT, font=("Segoe UI", 8))
        self._detail_id = self.create_text(18, 164, text="正在扫描 HID 设备…", anchor="nw", fill=MUTED, font=("Segoe UI", 8), width=242)
        self._time_id = self.create_text(260, 206, text="", anchor="se", fill=FAINT, font=("Segoe UI", 8))

    def set_label(self, text: str):
        if text and text != self.label:
            self.label = text
            self.itemconfigure(self._label_id, text=text)

    def set(self, reading: Reading):
        # Keep the level colour even for a last-known value; the status text and
        # the "(上次 xx%)" detail make staleness explicit.
        color = level_color(reading.percent, False)
        if reading.percent is None:
            self.itemconfigure(self._pct_id, text="--", fill=GRAY)
            self.itemconfigure(self._pct_suffix, text="", fill=GRAY)
            width = 0
        else:
            self.itemconfigure(self._pct_id, text=str(reading.percent), fill=color)
            self.itemconfigure(self._pct_suffix, text="%", fill=color)
            width = max(4, int((260 - 18) * reading.percent / 100))
        self.itemconfigure(self._status_id, text=reading.status_text, fill=color if reading.status == STATUS_OK else FAINT)
        name = reading.name or reading.label
        if len(name) > 30:
            name = name[:29] + "…"
        self.itemconfigure(self._name_id, text=name)
        self.itemconfigure(self._bar_fill, fill=color)
        self.coords(
            self._bar_fill,
            18, 128,
            18 + width, 128,
            18 + width, 138,
            18, 138,
        )
        self.itemconfigure(self._source_id, text=reading.source or "")
        detail = reading.detail or ("已读取" if reading.status == STATUS_OK else reading.status_text)
        self.itemconfigure(self._detail_id, text=detail)
        import time as _time

        self.itemconfigure(self._time_id, text=_time.strftime("%H:%M:%S", _time.localtime(reading.ts)))


class Panel:
    def __init__(
        self,
        root: tk.Tk,
        *,
        on_refresh: Callable[[], None],
        on_interval: Callable[[int], None],
        on_autostart: Callable[[bool], None],
        on_debug: Callable[[], None],
        on_close: Callable[[], None],
        on_exit: Callable[[], None],
        interval: int,
        autostart: bool,
    ):
        self.root = root
        self.on_refresh = on_refresh
        self.on_interval = on_interval
        self.on_autostart = on_autostart
        self.on_debug = on_debug
        self.on_close = on_close
        self.on_exit = on_exit
        self._updating_autostart = False

        root.title("2.4G 电量")
        root.configure(bg=BG)
        root.resizable(False, False)
        self._center(620, 410)

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", background="#2a2d33", foreground=FG, borderwidth=0, focusthickness=0, padding=(11, 6))
        style.map("TButton", background=[("active", "#383c44"), ("pressed", "#444954")])
        style.configure("TCheckbutton", background=BG, foreground=FG, focuscolor=BG)
        style.map("TCheckbutton", background=[("active", BG)], foreground=[("active", FG)])
        style.configure("TCombobox", fieldbackground="#2a2d33", background="#2a2d33", foreground=FG, arrowcolor=FG)
        style.map("TCombobox", fieldbackground=[("readonly", "#2a2d33")], foreground=[("readonly", FG)])

        header = tk.Frame(root, bg=BG)
        header.pack(fill="x", padx=18, pady=(14, 4))
        tk.Label(header, text="无线外设电量", bg=BG, fg=FG, font=("Segoe UI", 17, "bold")).pack(side="left")
        self.header_note = tk.Label(header, text="", bg=BG, fg=FAINT, font=("Segoe UI", 9))
        self.header_note.pack(side="right", pady=(6, 0))

        cards = tk.Frame(root, bg=BG)
        cards.pack(padx=18, pady=(8, 4))
        self.mouse_card = Card(cards, "鼠标")
        self.mouse_card.pack(side="left", padx=(0, 8))
        self.secondary_card = Card(cards, "键盘")
        self.secondary_card.pack(side="left", padx=(8, 0))

        controls = tk.Frame(root, bg=BG)
        controls.pack(fill="x", padx=18, pady=(4, 2))
        self.refresh_btn = ttk.Button(controls, text="立即刷新", command=self.on_refresh)
        self.refresh_btn.pack(side="left")
        tk.Label(controls, text="刷新间隔", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=(14, 5))
        self.interval_var = tk.StringVar()
        self.interval_box = ttk.Combobox(
            controls,
            textvariable=self.interval_var,
            values=[label for label, _ in INTERVAL_CHOICES],
            width=8,
            state="readonly",
        )
        self.interval_box.pack(side="left")
        self.interval_box.bind("<<ComboboxSelected>>", self._interval_selected)
        self.autostart_var = tk.BooleanVar(value=autostart)
        self.autostart_check = ttk.Checkbutton(
            controls, text="开机自启", variable=self.autostart_var, command=self._autostart_clicked
        )
        self.autostart_check.pack(side="left", padx=(16, 0))
        ttk.Button(controls, text="调试", command=self.on_debug).pack(side="right")
        ttk.Button(controls, text="退出", command=self.on_exit).pack(side="right", padx=(0, 8))

        self.status_var = tk.StringVar(value="正在扫描设备…")
        self.status_label = tk.Label(root, textvariable=self.status_var, bg=BG, fg=FAINT, font=("Segoe UI", 8), anchor="w")
        self.status_label.pack(fill="x", padx=19, pady=(2, 10))

        self.set_interval(interval)
        self.set_autostart(autostart)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _center(self, width: int, height: int):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, (sw - width) // 2)
        y = max(0, (sh - height) // 2 - 20)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def set_interval(self, seconds: int):
        best = min(INTERVAL_CHOICES, key=lambda pair: abs(pair[1] - seconds))
        self.interval_var.set(best[0])
        try:
            self.header_note.configure(text="每 " + best[0] + " 自动刷新")
        except Exception:
            pass

    def _interval_selected(self, _event=None):
        label = self.interval_var.get()
        for text, seconds in INTERVAL_CHOICES:
            if text == label:
                self.on_interval(seconds)
                return

    def set_autostart(self, enabled: bool):
        self._updating_autostart = True
        try:
            self.autostart_var.set(bool(enabled))
        finally:
            self._updating_autostart = False

    def _autostart_clicked(self):
        if self._updating_autostart:
            return
        self.on_autostart(bool(self.autostart_var.get()))

    def update_readings(self, rows: list[Reading]):
        by_slot = {r.slot: r for r in rows}
        mouse = by_slot.get("mouse")
        secondary = by_slot.get("secondary")
        if mouse:
            self.mouse_card.set(mouse)
        if secondary:
            # Keep the card title accurate if a DARKRIM headset is attached;
            # for the MCHOSE G98 V2 this is simply "键盘".
            self.secondary_card.set_label("耳机" if secondary.label == "耳机" else "键盘")
            self.secondary_card.set(secondary)
        bits = []
        for r in (mouse, secondary):
            if r is None:
                continue
            if r.percent is None:
                bits.append(f"{r.label} --")
            else:
                bits.append(f"{r.label} {r.percent}%")
        import time as _time

        self.status_var.set("上次刷新 " + _time.strftime("%H:%M:%S") + "  ·  " + "  ·  ".join(bits))
        self.header_note.configure(text="每 " + self._interval_human() + " 自动刷新")

    def _interval_human(self) -> str:
        label = self.interval_var.get()
        return label or "60 秒"

    def set_status(self, text: str):
        self.status_var.set(text)

    def show(self):
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.attributes("-topmost", True)
            self.root.after(120, lambda: self.root.attributes("-topmost", False))
        except Exception:
            pass
        try:
            self.root.focus_force()
        except Exception:
            pass

    def hide(self):
        self.root.withdraw()

    def visible(self) -> bool:
        try:
            return self.root.state() != "withdrawn"
        except Exception:
            return True
