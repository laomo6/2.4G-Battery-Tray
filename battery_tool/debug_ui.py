"""Full debug window: enumerate HID, dump reports, send frames, calibrate."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from . import protocols
from .config import Config
from .devices import DeviceManager
from .hid import HIDDevice, HIDInterface, enumerate_hid, hexs, find_first

BG = "#17181c"
PANEL = "#202227"
FG = "#e8eaed"
MUTED = "#9aa0aa"
ACCENT = "#3b82f6"


class DebugWindow(tk.Toplevel):
    def __init__(self, master, config: Config, manager: DeviceManager):
        super().__init__(master)
        self.config = config
        self.manager = manager
        self.title("完整调试版 · 2.4G 电量")
        self.configure(bg=BG)
        self.geometry("1120x720")
        self.minsize(900, 600)
        self._q: queue.Queue = queue.Queue()
        self._interfaces: list[HIDInterface] = []
        self._selected: HIDInterface | None = None
        self._busy = False
        self._build()
        self.refresh_list()
        self.after(100, self._pump)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # -- layout ----------------------------------------------------------
    def _build(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=22, borderwidth=0)
        style.configure("Treeview.Heading", background="#2a2d33", foreground=FG, relief="flat")
        style.map("Treeview", background=[("selected", "#2f4f7f")])
        style.configure("TButton", background="#2a2d33", foreground=FG, borderwidth=0, padding=(9, 5))
        style.map("TButton", background=[("active", "#3a3e47")])
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("TCombobox", fieldbackground="#2a2d33", background="#2a2d33", foreground=FG)

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(top, text="HID 接口", bg=BG, fg=FG, font=("Segoe UI", 12, "bold")).pack(side="left")
        ttk.Button(top, text="刷新列表", command=self.refresh_list).pack(side="left", padx=(12, 4))
        ttk.Button(top, text="读取两设备", command=self.read_devices).pack(side="left", padx=4)
        ttk.Button(top, text="复制选中路径", command=self.copy_path).pack(side="left", padx=4)
        tk.Label(top, text="所有操作只针对选中的接口；写操作会提示确认。", bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(side="right")

        columns = ("vidpid", "usage", "reports", "product", "path")
        tree_frame = tk.Frame(self, bg=BG)
        tree_frame.pack(fill="both", expand=False, padx=10)
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=10)
        headings = {
            "vidpid": ("VID:PID", 90),
            "usage": ("Usage", 90),
            "reports": ("In / Out / Feat", 110),
            "product": ("产品", 180),
            "path": ("设备路径", 620),
        }
        for key, (text, width) in headings.items():
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor="w", stretch=(key == "path"))
        ysb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        btns = tk.Frame(self, bg=BG)
        btns.pack(fill="x", padx=10, pady=(6, 2))
        ttk.Button(btns, text="转储 Feature Report", command=self.dump_feature).pack(side="left", padx=(0, 4))
        ttk.Button(btns, text="探测 Report ID", command=self.probe_report_ids).pack(side="left", padx=4)
        ttk.Button(btns, text="监听 Input Report", command=self.listen_input).pack(side="left", padx=4)
        ttk.Button(btns, text="试发 Output Report", command=self.send_output).pack(side="left", padx=4)
        ttk.Button(btns, text="试发 Feature Report", command=self.send_feature).pack(side="left", padx=4)
        ttk.Button(btns, text="清空输出", command=lambda: self.out.delete("1.0", "end")).pack(side="right")

        self.out = ScrolledText(self, bg="#0f1013", fg="#d7dbe0", insertbackground=FG, font=("Consolas", 9), height=14, relief="flat")
        self.out.pack(fill="both", expand=True, padx=10, pady=(4, 6))

        cal = tk.LabelFrame(self, text=" 手动标定 ", bg=BG, fg=FG, font=("Segoe UI", 9))
        cal.pack(fill="x", padx=10, pady=(0, 10))
        self.cal_slot = tk.StringVar(value="secondary")
        self.cal_transport = tk.StringVar(value="feature")
        self.cal_rid = tk.StringVar(value="0")
        self.cal_offset = tk.StringVar(value="1")
        self.cal_scale = tk.StringVar(value="raw")
        tk.Label(cal, text="卡片", bg=BG, fg=MUTED).grid(row=0, column=0, padx=4, pady=4)
        ttk.Combobox(cal, textvariable=self.cal_slot, values=["mouse", "secondary"], width=9, state="readonly").grid(row=0, column=1)
        tk.Label(cal, text="来源", bg=BG, fg=MUTED).grid(row=0, column=2, padx=(12, 4))
        ttk.Combobox(cal, textvariable=self.cal_transport, values=["feature", "input"], width=8, state="readonly").grid(row=0, column=3)
        tk.Label(cal, text="Report ID", bg=BG, fg=MUTED).grid(row=0, column=4, padx=(12, 4))
        tk.Entry(cal, textvariable=self.cal_rid, width=6, bg="#2a2d33", fg=FG, insertbackground=FG).grid(row=0, column=5)
        tk.Label(cal, text="字节下标", bg=BG, fg=MUTED).grid(row=0, column=6, padx=(12, 4))
        tk.Entry(cal, textvariable=self.cal_offset, width=5, bg="#2a2d33", fg=FG, insertbackground=FG).grid(row=0, column=7)
        tk.Label(cal, text="倍率", bg=BG, fg=MUTED).grid(row=0, column=8, padx=(12, 4))
        ttk.Combobox(cal, textvariable=self.cal_scale, values=["raw", "255", "200"], width=7, state="readonly").grid(row=0, column=9)
        ttk.Button(cal, text="保存", command=self.save_calibration).grid(row=0, column=10, padx=(12, 4))
        ttk.Button(cal, text="读取测试", command=self.test_calibration).grid(row=0, column=11, padx=4)
        ttk.Button(cal, text="清除", command=self.clear_calibration).grid(row=0, column=12, padx=4)

    # -- helpers ---------------------------------------------------------
    def log(self, text: str):
        self.out.insert("end", text.rstrip() + "\n")
        self.out.see("end")

    def _run(self, fn, name="debug"):
        if self._busy:
            self.log("! 上一个操作还在进行，请稍等")
            return
        self._busy = True

        def worker():
            try:
                fn()
            except Exception as exc:
                self._q.put(("log", f"! {type(exc).__name__}: {exc}"))
            finally:
                self._q.put(("done", None))

        threading.Thread(target=worker, name=name, daemon=True).start()

    def _pump(self):
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "done":
                    self._busy = False
                elif kind == "list":
                    self._fill_tree(payload)
                elif kind == "readings":
                    self._show_readings(payload)
        except queue.Empty:
            pass
        try:
            self.after(100, self._pump)
        except tk.TclError:
            pass

    def _fill_tree(self, interfaces):
        self._interfaces = interfaces
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, it in enumerate(interfaces):
            self.tree.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    it.vidpid,
                    f"0x{it.usage_page:04X}/0x{it.usage:04X}",
                    f"{it.input_len} / {it.output_len} / {it.feature_len}",
                    it.product or it.manufacturer,
                    it.path,
                ),
            )
        self.log(f"枚举到 {len(interfaces)} 个 HID 接口。")

    # -- actions ---------------------------------------------------------
    def refresh_list(self):
        def work():
            self._q.put(("list", enumerate_hid()))

        self._run(work, "enumerate")

    def _on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self._interfaces):
            self._selected = self._interfaces[idx]
            it = self._selected
            self.log(
                f"\n选中: {it.vidpid}  Usage=0x{it.usage_page:04X}/0x{it.usage:04X}  "
                f"In={it.input_len} Out={it.output_len} Feat={it.feature_len}\n"
                f"  {it.product!r}  {it.manufacturer!r}\n  {it.path}"
            )

    def copy_path(self):
        if self._selected:
            self.clipboard_clear()
            self.clipboard_append(self._selected.path)
            self.log("已复制路径。")

    def dump_feature(self):
        it = self._selected
        if not it:
            self.log("! 先选一个接口")
            return
        if it.feature_len <= 0:
            self.log("! 该接口没有 Feature Report")
            return

        def work():
            self.log(f"\n=== Feature dump {it.vidpid} len={it.feature_len} ===")
            with HIDDevice(it) as dev:
                for rid in range(0, 33):
                    r = dev.get_feature(rid)
                    if r:
                        self._q.put(("log", f"rid {rid:02X}: {hexs(r, 96)}"))

        self._run(work, "feature-dump")

    def probe_report_ids(self):
        it = self._selected
        if not it:
            self.log("! 先选一个接口")
            return

        def work():
            self.log(
                f"\n=== Report ID probe {it.vidpid} "
                f"(In={it.input_len} Out={it.output_len} Feat={it.feature_len}) ==="
            )
            with HIDDevice(it) as dev:
                if it.feature_len > 0:
                    found = 0
                    for rid in range(256):
                        r = dev.get_feature(rid)
                        if r:
                            found += 1
                            self._q.put(("log", f"Feature rid {rid:02X}: {hexs(r, 32)}"))
                    self._q.put(("log", f"Feature 命中 {found} 个 Report ID"))
                if it.input_len > 0:
                    self._q.put(("log", "Input 监听 3 秒（只读）…"))
                    seen = {}
                    for r in dev.read_for(3.0, 120):
                        key = r[:1].hex() if r else "?"
                        seen[key] = seen.get(key, 0) + 1
                        self._q.put(("log", f"Input {len(r):02d}: {hexs(r, 64)}"))
                    self._q.put(("log", f"Input Report ID 统计: {seen}"))
                if it.output_len > 0:
                    self._q.put(("log", "Output Report ID 不主动盲发（避免误改设置），可手工试发。"))

        self._run(work, "report-probe")

    def listen_input(self):
        it = self._selected
        if not it:
            self.log("! 先选一个接口")
            return
        if it.input_len <= 0:
            self.log("! 该接口没有 Input Report")
            return

        def work():
            self.log(f"\n=== Input listen 5s {it.vidpid} len={it.input_len} ===")
            with HIDDevice(it) as dev:
                for r in dev.read_for(5.0, 200):
                    self._q.put(("log", f"{len(r):02d}: {hexs(r, 96)}"))

        self._run(work, "input-listen")

    def send_output(self):
        it = self._selected
        if not it:
            self.log("! 先选一个接口")
            return
        text = simpledialog.askstring(
            "试发 Output Report",
            "十六进制字节（可带空格，例如 13 4A 01 ...）。\n会先确认再发送。",
            parent=self,
        )
        if not text:
            return
        data = _parse_hex(text)
        if data is None:
            self.log("! HEX 格式错误")
            return
        if not messagebox.askyesno("确认", f"向 {it.vidpid} 发送 {len(data)} 字节 Output Report？", parent=self):
            return

        def work():
            self.log(f"\nTX Output {it.vidpid}: {hexs(data)}")
            with HIDDevice(it) as dev:
                ok = dev.write_output(data, 800)
                self._q.put(("log", f"write_output -> {ok}"))
                if ok:
                    for r in dev.read_for(2.0, 60):
                        self._q.put(("log", f"RX {len(r):02d}: {hexs(r, 96)}"))

        self._run(work, "send-output")

    def send_feature(self):
        it = self._selected
        if not it:
            self.log("! 先选一个接口")
            return
        text = simpledialog.askstring(
            "试发 Feature Report",
            "十六进制字节，第一个字节就是 Report ID。",
            parent=self,
        )
        if not text:
            return
        data = _parse_hex(text)
        if data is None:
            self.log("! HEX 格式错误")
            return
        if not messagebox.askyesno("确认", f"向 {it.vidpid} 发送 {len(data)} 字节 Feature Report？", parent=self):
            return

        def work():
            self.log(f"\nTX Feature {it.vidpid}: {hexs(data)}")
            with HIDDevice(it) as dev:
                self._q.put(("log", f"set_feature -> {dev.set_feature(data)}"))
                rid = data[0] if data else 0
                r = dev.get_feature(rid)
                self._q.put(("log", f"get_feature({rid:02X}) -> {hexs(r, 128) if r else None}"))

        self._run(work, "send-feature")

    def read_devices(self):
        def work():
            self._q.put(("log", "=== 读取两设备 ==="))
            for r in self.manager.read_all():
                self._q.put(("log", f"{r.label}: {r.name}  {r.percent}%  {r.status}  {r.detail}  [{r.source}]"))
            self._q.put(("readings", None))

        self._run(work, "read-devices")

    def _show_readings(self, _payload):
        pass

    # -- calibration -----------------------------------------------------
    def _cal_value(self) -> dict | None:
        it = self._selected
        if not it:
            self.log("! 手动标定需要先选中一个接口")
            return None
        try:
            rid = int(self.cal_rid.get(), 0)
            offset = int(self.cal_offset.get(), 0)
        except ValueError:
            self.log("! Report ID / 下标必须是整数")
            return None
        return {
            "vid": it.vid,
            "pid": it.pid,
            "transport": self.cal_transport.get(),
            "report_id": rid,
            "offset": offset,
            "scale": self.cal_scale.get(),
        }

    def save_calibration(self):
        value = self._cal_value()
        if not value:
            return
        slot = self.cal_slot.get()
        self.config.set_calibration(slot, value)
        self.log(f"已保存 {slot} 标定: {value}")

    def clear_calibration(self):
        slot = self.cal_slot.get()
        self.config.set_calibration(slot, None)
        self.log(f"已清除 {slot} 标定")

    def test_calibration(self):
        value = self._cal_value()
        if not value:
            return
        slot = self.cal_slot.get()

        def work():
            ifaces = enumerate_hid()
            r = protocols.calibrated_read(ifaces, value, slot, "手动标定")
            if r:
                self._q.put(("log", f"标定测试: {r.percent}%  raw={hexs(r.raw or b'', 32)}"))
            else:
                self._q.put(("log", "标定测试失败：读不到数据或数据越界"))

        self._run(work, "calibration-test")


def _parse_hex(text: str) -> bytes | None:
    cleaned = text.replace(",", " ").replace("0x", " ").replace("0X", " ")
    parts = cleaned.split()
    try:
        out = bytearray()
        for p in parts:
            if not p:
                continue
            if len(p) > 2:
                # allow continuous strings such as 134a01
                for i in range(0, len(p), 2):
                    out.append(int(p[i : i + 2], 16))
            else:
                out.append(int(p, 16))
        return bytes(out)
    except ValueError:
        return None
