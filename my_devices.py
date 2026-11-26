#!/usr/bin/env python3
"""Windows 10/11 wireless peripheral battery tray.

Zero third-party dependencies: Python standard library + ctypes + tkinter.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as w
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _enable_dpi():
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        try:
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            user32.SetProcessDPIAware()
    except Exception:
        pass


def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _fmt_reading(r, debug=False) -> str:
    label = r.label
    name = r.name or ""
    if r.percent is None:
        body = "—"
        extra = f"（{r.detail or r.status_text}）"
    else:
        body = f"{r.percent}%"
        if r.stale:
            body = f"~{body}"
        extra = f"（{r.detail}）" if (r.detail or debug) else ""
    source = f" · {r.source}" if (r.source or debug) else ""
    return f"{label} {name}：{body}{extra}{source}"


def _apply_last(config, rows):
    # DeviceManager already does this; kept for clarity when only --once is used.
    return rows


def cmd_once(args) -> int:
    from battery_tool.config import Config
    from battery_tool.devices import DeviceManager

    config = Config()
    manager = DeviceManager(config)
    rows = manager.read_all()
    while len(rows) < 2:
        from battery_tool.protocols import Reading

        rows.append(Reading("secondary" if len(rows) else "mouse", "设备", "未找到", status="missing"))
    for r in rows[:2]:
        print(_fmt_reading(r, args.debug))
    return 0


def cmd_list(args) -> int:
    from battery_tool.hid import enumerate_hid

    rows = enumerate_hid()
    print(f"{'VID:PID':10} {'Usage':14} {'In':>4} {'Out':>4} {'Feat':>5}  Product / Path")
    for it in rows:
        print(
            f"{it.vidpid:10} 0x{it.usage_page:04X}/0x{it.usage:04X} "
            f"{it.input_len:4d} {it.output_len:4d} {it.feature_len:5d}  "
            f"{it.product or it.manufacturer}  {it.path}"
        )
    print(f"\n共 {len(rows)} 个 HID 接口")
    return 0


def cmd_install(args) -> int:
    from battery_tool.install import install_all

    for line in install_all():
        print(line)
    return 0


def cmd_uninstall(args) -> int:
    from battery_tool.install import uninstall_all

    for line in uninstall_all():
        print(line)
    return 0


_MUTEX = None


def _single_instance() -> bool:
    global _MUTEX
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
    kernel32.CreateMutexW.restype = w.HANDLE
    _MUTEX = kernel32.CreateMutexW(None, False, "Local\\2.4GBatteryTray_SingleInstance")
    if not _MUTEX:
        return True
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def _show_existing() -> bool:
    try:
        from battery_tool.tray import signal_existing

        if signal_existing():
            return True
    except Exception:
        pass
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.MessageBoxW(None, "电量托盘已经在运行（可能是面板模式）。", "2.4G 电量", 0x40)
    except Exception:
        pass
    return False


def cmd_gui(args) -> int:
    if not _single_instance():
        _show_existing()
        return 0
    from battery_tool.app import App

    tray_mode = not args.panel
    show_panel = not args.tray
    if args.debug:
        tray_mode = False
        show_panel = True
    app = App(tray_mode=tray_mode, show_panel=show_panel, debug=args.debug, interval=args.interval)
    if args.debug:
        print("调试模式：控制台输出已开启；主面板与调试窗口已打开。", flush=True)
    app.run()
    return 0


def main(argv=None) -> int:
    _enable_dpi()
    _utf8_stdout()
    parser = argparse.ArgumentParser(
        description="2.4G 无线外设电量托盘（纯 Python + ctypes + tkinter）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python my_devices.py            打开面板并常驻托盘\n"
            "  python my_devices.py --tray     只常驻托盘\n"
            "  python my_devices.py --panel    只开面板\n"
            "  python my_devices.py --once     读一次并打印两行\n"
            "  python my_devices.py --debug    完整调试版 + 控制台输出\n"
            "  python my_devices.py --install  创建开机自启和桌面链接\n"
        ),
    )
    parser.add_argument("--once", action="store_true", help="读取一次并打印两行")
    parser.add_argument("--list", action="store_true", help="列出所有 HID 接口")
    parser.add_argument("--install", action="store_true", help="创建启动文件夹快捷方式和桌面链接")
    parser.add_argument("--uninstall", action="store_true", help="删除本工具创建的启动项和桌面链接")
    parser.add_argument("--panel", action="store_true", help="只开简洁面板，不常驻托盘")
    parser.add_argument("--tray", action="store_true", help="只常驻托盘，面板隐藏")
    parser.add_argument("--debug", action="store_true", help="完整调试版，并保留控制台输出")
    parser.add_argument("--interval", type=int, default=None, help="刷新间隔秒数（30-1800）")
    args = parser.parse_args(argv)

    if args.once:
        return cmd_once(args)
    if args.list:
        return cmd_list(args)
    if args.install:
        return cmd_install(args)
    if args.uninstall:
        return cmd_uninstall(args)
    return cmd_gui(args)


if __name__ == "__main__":
    try:
        _code = main()
    except SystemExit:
        raise
    except Exception:
        import traceback

        _text = traceback.format_exc()
        try:
            ctypes.windll.user32.MessageBoxW(None, _text[-1800:], "2.4G 电量启动失败", 0x10)
        except Exception:
            pass
        print(_text, file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(_code)
