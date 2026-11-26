"""Pick the two devices for the panel and read them concurrently."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

from . import protocols
from .config import Config
from .hid import HIDInterface, enumerate_hid, find_first
from .protocols import Reading, STATUS_ASLEEP, STATUS_ERROR, STATUS_MISSING, STATUS_OK


class DeviceManager:
    def __init__(self, config: Config):
        self.config = config

    def _pick(self, interfaces: list[HIDInterface]):
        g502 = find_first(interfaces, vid=0x046D, pid=0xC539, usage_page=0xFF00, exact_output=20)
        atk = find_first(interfaces, usage_page=0xFF05, exact_input=64, exact_output=64)
        mchose = find_first(interfaces, vid=0x41E4, pid=0x2004, usage_page=0xFF02, exact_output=20)
        darkrim = find_first(interfaces, vid=0x3654)
        return g502, atk, mchose, darkrim

    def read_all(self) -> list[Reading]:
        interfaces = enumerate_hid()
        g502, atk, mchose, darkrim = self._pick(interfaces)

        mouse_cal = self.config.calibration("mouse")
        secondary_cal = self.config.calibration("secondary")

        def read_mouse() -> Reading:
            try:
                if g502 is not None:
                    return protocols.logitech_read(interfaces)
                if atk is not None:
                    return protocols.atk_read(interfaces)
                if mouse_cal:
                    value = protocols.calibrated_read(interfaces, mouse_cal, "mouse", "鼠标")
                    if value:
                        return value
                value = protocols.standard_read(interfaces, "mouse")
                if value:
                    return value
                return Reading("mouse", "鼠标", "未找到鼠标", status=STATUS_MISSING, detail="请插入设备或拔插一次")
            except Exception as exc:
                return Reading("mouse", "鼠标", "鼠标", status=STATUS_ERROR, detail=f"{type(exc).__name__}: {exc}")

        def read_secondary() -> Reading:
            try:
                if mchose is not None:
                    return protocols.mchose_read(interfaces)
                if darkrim is not None:
                    return protocols.darkrim_read(interfaces)
                if secondary_cal:
                    value = protocols.calibrated_read(interfaces, secondary_cal, "secondary", "键盘")
                    if value:
                        return value
                value = protocols.standard_read(interfaces, "secondary")
                if value:
                    return value
                return Reading("secondary", "键盘", "未找到设备", status=STATUS_MISSING, detail="请插入设备或拔插一次")
            except Exception as exc:
                return Reading("secondary", "键盘", "设备", status=STATUS_ERROR, detail=f"{type(exc).__name__}: {exc}")

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(read_mouse)
            f2 = pool.submit(read_secondary)
            rows = [f1.result(), f2.result()]

        # Keep the two cards stable even if a protocol changed the label.
        rows[0].slot = "mouse"
        rows[0].label = "鼠标"
        rows[1].slot = "secondary"
        if rows[1].label not in ("耳机",):
            rows[1].label = "键盘"

        for row in rows:
            custom = self.config.display_name(row.slot)
            if custom:
                row.name = custom
            if row.status == STATUS_OK and row.percent is not None:
                self.config.set_last(row.slot, row.percent, row.ts)
            elif row.percent is None:
                last = self.config.last(row.slot)
                if last and isinstance(last.get("percent"), int):
                    row.percent = int(last["percent"])
                    row.stale = True
                    suffix = f"（上次 {row.percent}%）"
                    row.detail = (row.detail + " " + suffix).strip()
        return rows

    def list_interfaces(self) -> list[HIDInterface]:
        return enumerate_hid()
