"""Device protocols.

The two protocols that are known byte-for-byte are implemented first:

* ATK / VXE Nordic mouse:  usage page 0xFF05, report id 0x08, 64 byte reports
* DARKRIM JL_RCSP headset: VID 0x3654, 65 byte reports, CRC16-CCITT-FALSE

The two devices actually attached to this machine get dedicated readers too:

* Logitech G502 LIGHTSPEED (receiver 046D:C539): HID++ 2.0 feature 0x1001
* MCHOSE G98 V2 (receiver 41E4:2004): Sinowealth 0x13 report, getBattery 0x4A
  and the 0x0A/0x05 battery notification.

Nothing is written to the devices except read-only queries.  Voltage to
percentage uses a LiPo discharge curve because the G502 only exposes voltage.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable

from .hid import HIDDevice, HIDInterface, find_first

STATUS_OK = "ok"
STATUS_ASLEEP = "asleep"
STATUS_MISSING = "missing"
STATUS_ERROR = "error"
STATUS_UNSUPPORTED = "unsupported"


@dataclass
class Reading:
    slot: str
    label: str
    name: str
    percent: int | None = None
    charging: bool = False
    status: str = STATUS_MISSING
    detail: str = ""
    source: str = ""
    raw: bytes | None = None
    stale: bool = False
    ts: float = field(default_factory=time.time)

    @property
    def status_text(self) -> str:
        if self.status == STATUS_OK:
            return "充电中" if self.charging else "已更新"
        if self.status == STATUS_ASLEEP:
            return "休眠/未上报"
        if self.status == STATUS_MISSING:
            return "未连接"
        if self.status == STATUS_UNSUPPORTED:
            return "协议未知"
        return "读取失败"

    def to_dict(self) -> dict:
        return {
            "slot": self.slot,
            "label": self.label,
            "name": self.name,
            "percent": self.percent,
            "charging": self.charging,
            "status": self.status,
            "detail": self.detail,
            "source": self.source,
            "stale": self.stale,
            "ts": self.ts,
        }


# ---------------------------------------------------------------------------
# helpers


def clamp_percent(v: float | int | None) -> int | None:
    if v is None:
        return None
    try:
        n = int(round(float(v)))
    except Exception:
        return None
    if n < 0 or n > 100:
        return None
    return n


def voltage_to_percent(mv: int) -> int:
    """Logitech/Solaar LiPo curve for the G502's reported millivolts.

    Solaar's ``estimate_battery_level_percentage`` table, with a small +0.4
    calibration to match G HUB: 3.773 V -> 39%, 3.956 V -> 75%,
    3.960 V -> 76% on this G502.
    """
    if mv <= 0:
        return 0
    points = [
        (4186, 100),
        (4067, 90),
        (3989, 80),
        (3922, 70),
        (3859, 60),
        (3811, 50),
        (3778, 40),
        (3751, 30),
        (3717, 20),
        (3671, 10),
        (3646, 5),
        (3579, 2),
        (3500, 0),
    ]
    if mv >= points[0][0]:
        return 100
    if mv <= points[-1][0]:
        return 0
    for (hi_v, hi_p), (lo_v, lo_p) in zip(points, points[1:]):
        if hi_v >= mv >= lo_v:
            span = hi_v - lo_v
            if span == 0:
                return hi_p
            # Solaar's interpolation with a +0.4 G HUB calibration.
            # 3.773 V -> 39%, 3.956 V -> 75%, 3.960 V -> 76%.
            return int(round(lo_p + (mv - lo_v) * (hi_p - lo_p) / span + 0.4))
    return 0


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc & 0xFFFF


def _name_from_product(iface: HIDInterface | None, fallback: str) -> str:
    if iface and iface.product and iface.product.lower() not in ("usb receiver", "hid-compliant device"):
        return iface.product
    return fallback


# ---------------------------------------------------------------------------
# Logitech HID++ 2.0


_LG_CACHE: dict[str, object] = {"index": None, "feature": None}


def _lg_request(dev: HIDDevice, index: int, feature: int, func: int, params: bytes = b"", timeout_s: float = 0.55):
    swid = 0x0A
    frame = bytearray(20)
    frame[0] = 0x11
    frame[1] = index
    frame[2] = feature
    frame[3] = (func << 4) | swid
    frame[4 : 4 + len(params)] = params[:16]
    if not dev.write_output(bytes(frame), 700):
        return None
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = dev.read_input(250)
        if not r or len(r) < 7:
            continue
        # Responses also arrive for notifications with another feature/function.
        if r[0] == 0x11 and r[1] == index and r[3] == ((func << 4) | swid):
            return r
    return None


def _lg_get_feature(dev: HIDDevice, index: int, feature_id: int, timeout_s: float = 0.55):
    params = bytes([(feature_id >> 8) & 0xFF, feature_id & 0xFF])
    r = _lg_request(dev, index, 0x00, 0x00, params, timeout_s)
    if not r or len(r) < 6:
        return None
    fi = r[4]
    if fi == 0:
        return 0
    return fi


def logitech_read(interfaces: Iterable[HIDInterface]) -> Reading:
    iface = find_first(interfaces, vid=0x046D, pid=0xC539, usage_page=0xFF00, exact_output=20)
    if iface is None:
        iface = find_first(interfaces, vid=0x046D, usage_page=0xFF00, exact_output=20)
    if iface is None:
        return Reading("mouse", "鼠标", "G502 LIGHTSPEED", status=STATUS_MISSING, detail="未找到 LIGHTSPEED 接收器")
    name = "G502 LIGHTSPEED"
    with HIDDevice(iface) as dev:
        # Find the paired device index once.  Index 1 is normal for a G502.
        candidates = []
        cached = _LG_CACHE.get("index")
        if isinstance(cached, int):
            candidates.append(cached)
        candidates.extend([1, 2, 3, 4, 0xFF])
        seen = set()
        chosen = None
        for idx in candidates:
            if idx in seen:
                continue
            seen.add(idx)
            fi = _lg_get_feature(dev, idx, 0x1001, 0.45)
            if fi:
                chosen = (idx, fi)
                break
        if chosen is None:
            return Reading(
                "mouse",
                "鼠标",
                name,
                status=STATUS_ASLEEP,
                detail="接收器无应答，动一下鼠标后重试",
                source="HID++ 2.0",
            )
        idx, _ = chosen
        _LG_CACHE["index"] = idx

        # 0x1000 -> percentage directly (some mice)
        fi = _lg_get_feature(dev, idx, 0x1000)
        if fi:
            r = _lg_request(dev, idx, fi, 0)
            if r and len(r) >= 7 and 0 <= r[4] <= 100:
                level = r[4]
                status = r[6] if len(r) > 6 else 0
                return Reading(
                    "mouse",
                    "鼠标",
                    name,
                    percent=level,
                    charging=status in (1, 2),
                    status=STATUS_OK,
                    detail=f"电量 {level}%",
                    source="HID++ 2.0 · 0x1000",
                    raw=bytes(r),
                )

        # 0x1004 -> unified battery (voltage + level)
        fi = _lg_get_feature(dev, idx, 0x1004)
        if fi:
            r = _lg_request(dev, idx, fi, 0)
            if r and len(r) >= 7:
                mv = (r[4] << 8) | r[5]
                level = r[6]
                if 0 <= level <= 100:
                    return Reading(
                        "mouse",
                        "鼠标",
                        name,
                        percent=level,
                        charging=(len(r) > 7 and r[7] in (1, 2)),
                        status=STATUS_OK,
                        detail=f"{mv} mV · 0x1004",
                        source="HID++ 2.0 · 0x1004",
                        raw=bytes(r),
                    )

        # 0x1001 -> battery voltage (G502 LIGHTSPEED)
        fi = _lg_get_feature(dev, idx, 0x1001)
        if fi:
            r = _lg_request(dev, idx, fi, 0)
            if r and len(r) >= 7:
                mv = (r[4] << 8) | r[5]
                status = r[6]
                level = voltage_to_percent(mv)
                return Reading(
                    "mouse",
                    "鼠标",
                    name,
                    percent=level,
                    charging=status in (1, 2),
                    status=STATUS_OK,
                    detail=f"{mv / 1000:.3f} V · 估算",
                    source="HID++ 2.0 · 0x1001 电压",
                    raw=bytes(r),
                )
        return Reading(
            "mouse",
            "鼠标",
            name,
            status=STATUS_UNSUPPORTED,
            detail="HID++ 已连接，但没有电量特性",
            source="HID++ 2.0",
        )


# ---------------------------------------------------------------------------
# MCHOSE G98 V2 (Sinowealth wireless)


def _mchose_frame(cmd: int, sub: int = 0x01) -> bytes:
    frame = bytes([0x13, cmd, sub, 0x00]) + bytes(15)
    return frame + bytes([sum(frame) & 0xFF])


def mchose_read(interfaces: Iterable[HIDInterface]) -> Reading:
    iface = find_first(interfaces, vid=0x41E4, pid=0x2004, usage_page=0xFF02, exact_output=20)
    if iface is None:
        iface = find_first(interfaces, vid=0x41E4, usage_page=0xFF02, exact_output=20)
    if iface is None:
        # Wired G98 V2: 0x41E4:0x2203 exposes a 519-byte feature report.
        wired = find_first(interfaces, vid=0x41E4, pid=0x2203)
        if wired is not None and wired.feature_len >= 32:
            with HIDDevice(wired) as dev:
                data = bytes([0x06, 0x87, 0x00, 0x00, 0x01, 0x00, 0x02, 0x00]) + bytes(max(0, wired.feature_len - 8))
                if dev.set_feature(data):
                    resp = dev.get_feature(0x06)
                    if resp and len(resp) >= 10:
                        # command(1) + space0(6) + level + flags
                        level = resp[7]
                        flags = resp[8]
                        if 0 <= level <= 100:
                            return Reading(
                                "secondary",
                                "键盘",
                                "MCHOSE G98 V2",
                                percent=level,
                                charging=(flags & 0x0F) in (1, 2),
                                status=STATUS_OK,
                                detail="USB 有线模式",
                                source="MCHOSE · Feature 0x06 0x87",
                            )
        return Reading("secondary", "键盘", "MCHOSE G98 V2", status=STATUS_MISSING, detail="未找到 2.4G 接收器")
    name = "MCHOSE G98 V2"
    with HIDDevice(iface) as dev:
        # getBattery: 13 4A 01 00 ...  Send only this first: the receiver's
        # input queue can otherwise overwrite the 4A reply with 07/05 replies.
        ack_type = None
        other: list[bytes] = []

        def consume(r: bytes):
            nonlocal ack_type
            if not r or len(r) < 8 or r[0] != 0x13:
                return None
            if r[1] == 0x0A and r[5] == 0x05:
                level, flags = r[6], r[7]
                if 0 <= level <= 100:
                    return Reading(
                        "secondary",
                        "键盘",
                        name,
                        percent=level,
                        charging=(flags & 0x0F) in (1, 2),
                        status=STATUS_OK,
                        detail=f"电池通知 · 状态 0x{flags:02X}",
                        source="MCHOSE 0x13 · 0x0A/0x05",
                        raw=bytes(r),
                    )
            if r[1] == 0x4A:
                ack_type = r[4] if len(r) > 4 else None
                # G98 V2 direct reply:
                #   13 4A 01 00 02 14 ... -> state 0x02, level 0x14 = 20%
                if len(r) >= 6 and 0 <= r[5] <= 100:
                    raw_level, state = r[5], r[4]
                    # The vendor HUB displays 10% steps, rounded to nearest:
                    # raw 44 -> 40%, raw 56 -> 60%, raw 50 -> 50%.
                    # Keep the raw value in the detail.
                    level = min(100, ((raw_level + 5) // 10) * 10)
                    return Reading(
                        "secondary",
                        "键盘",
                        name,
                        percent=level,
                        charging=state in (1, 3),
                        status=STATUS_OK,
                        detail=f"0x4A 原始 {raw_level}% · 官方 10% 档位",
                        source="MCHOSE 0x13 · 0x4A",
                        raw=bytes(r),
                    )
            return None

        for phase in (0, 1):
            if phase == 0:
                dev.write_output(_mchose_frame(0x4A), 700)
            else:
                dev.write_output(_mchose_frame(0x07), 700)
                dev.write_output(_mchose_frame(0x05), 700)
            deadline = time.monotonic() + (1.8 if phase == 0 else 1.0)
            while time.monotonic() < deadline:
                r = dev.read_input(200)
                if not r:
                    continue
                other.append(r)
                result = consume(r)
                if result is not None:
                    return result
        if ack_type is not None:
            return Reading(
                "secondary",
                "键盘",
                name,
                status=STATUS_ASLEEP,
                detail=f"接收器已应答，但未解析到电量（状态 0x{ack_type:02X}）",
                source="MCHOSE 0x13 · 0x4A",
                raw=other[-1] if other else None,
            )
        return Reading(
            "secondary",
            "键盘",
            name,
            status=STATUS_ASLEEP,
            detail="未收到电池通知，按任意键唤醒键盘后刷新",
            source="MCHOSE 0x13",
            raw=other[-1] if other else None,
        )


# ---------------------------------------------------------------------------
# ATK / VXE Nordic mouse


def atk_read(interfaces: Iterable[HIDInterface]) -> Reading:
    iface = find_first(interfaces, usage_page=0xFF05, exact_input=64, exact_output=64)
    if iface is None:
        return Reading("mouse", "鼠标", "ATK / VXE", status=STATUS_MISSING, detail="未找到 0xFF05 厂商接口")
    name = _name_from_product(iface, "ATK / VXE 鼠标")
    frame = bytearray(64)
    frame[0:8] = bytes([0x08, 0x7D, 0x72, 0x02, 0x00, 0x01, 0x07, 0x01])
    with HIDDevice(iface) as dev:
        for _ in range(2):
            if not dev.write_output(bytes(frame), 700):
                break
            for r in dev.read_for(0.9, 8):
                if len(r) >= 8 and r[1] == 0x72 and r[5] == 0x07:
                    level = r[7]
                    if 0 <= level <= 100:
                        return Reading(
                            "mouse",
                            "鼠标",
                            name,
                            percent=level,
                            status=STATUS_OK,
                            detail="Report 0x08",
                            source="ATK Nordic · 0xFF05",
                            raw=bytes(r),
                        )
    return Reading(
        "mouse",
        "鼠标",
        name,
        status=STATUS_ASLEEP,
        detail="鼠标休眠，动一下鼠标后刷新",
        source="ATK Nordic · 0xFF05",
    )


# ---------------------------------------------------------------------------
# DARKRIM JL_RCSP headset


_DARKRIM_SEQ = 0


def _darkrim_query() -> bytes:
    global _DARKRIM_SEQ
    _DARKRIM_SEQ = (_DARKRIM_SEQ + 1) & 0xFF
    frame = bytearray(65)
    frame[0] = 0x00
    frame[1] = 0xFE
    frame[2] = _DARKRIM_SEQ
    frame[3] = 0x10
    frame[4] = 0x00
    frame[5] = 0x02
    frame[6] = 0x00
    frame[7] = 0x00
    # TLV length = 0 at frame[8..9]; CRC covers frame[1:10].
    crc = crc16_ccitt_false(bytes(frame[1:10]))
    frame[10] = (crc >> 8) & 0xFF
    frame[11] = crc & 0xFF
    return bytes(frame)


def _parse_tlv(payload: bytes) -> dict[int, bytes]:
    out: dict[int, bytes] = {}
    i = 0
    while i + 2 <= len(payload):
        typ = payload[i]
        ln = payload[i + 1]
        if i + 2 + ln > len(payload):
            break
        out.setdefault(typ, payload[i + 2 : i + 2 + ln])
        i += 2 + ln
    return out


def darkrim_read(interfaces: Iterable[HIDInterface]) -> Reading:
    iface = find_first(interfaces, vid=0x3654, min_input=64)
    if iface is None:
        iface = find_first(interfaces, vid=0x3654)
    if iface is None:
        return Reading("secondary", "耳机", "DARKRIM SHADOW", status=STATUS_MISSING, detail="未找到 DARKRIM 接收器")
    name = "DARKRIM SHADOW"
    frame = _darkrim_query()
    with HIDDevice(iface) as dev:
        # No report id: Windows may expect a leading 0 when caps includes the
        # report-number byte (65 payload + 1 zero).
        payload = (b"\x00" + frame) if iface.output_len >= 66 else frame
        sent = dev.write_output(payload, 800)
        if not sent:
            sent = dev.set_feature(payload, len(payload))
        if not sent:
            return Reading(
                "secondary",
                "耳机",
                name,
                status=STATUS_ERROR,
                detail="无法发送查询帧",
                source="JL_RCSP",
            )
        for r in dev.read_for(1.5, 30):
            r = bytes(r)
            if len(r) >= 3 and r[0] == 0 and r[1] == 0 and r[2] == 0xFE:
                r = r[1:]
            if len(r) < 12 or r[1] != 0xFE:
                continue
            length = r[8] | (r[9] << 8)
            if 10 + length > len(r):
                continue
            payload = bytes(r[10 : 10 + length])
            tlvs = _parse_tlv(payload)
            if 0x02 in tlvs:
                try:
                    name = tlvs[0x02].decode("utf-8", "ignore").strip("\x00 ") or name
                except Exception:
                    pass
            if 0x01 in tlvs and tlvs[0x01]:
                level = tlvs[0x01][0]
                if 0 <= level <= 100:
                    extra = []
                    if 0x04 in tlvs:
                        extra.append(_ascii(tlvs[0x04]))
                    if 0x05 in tlvs:
                        extra.append(_ascii(tlvs[0x05]))
                    return Reading(
                        "secondary",
                        "耳机",
                        name,
                        percent=level,
                        status=STATUS_OK,
                        detail=" · ".join(x for x in extra if x) or "TLV 0x01",
                        source="JL_RCSP · TLV 0x01",
                        raw=bytes(r),
                    )
    return Reading(
        "secondary",
        "耳机",
        name,
        status=STATUS_ASLEEP,
        detail="耳机未开机或未连接 2.4G",
        source="JL_RCSP",
    )


def _ascii(data: bytes) -> str:
    try:
        return data.rstrip(b"\x00").decode("ascii", "ignore")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Standard HID battery + manual calibration


def standard_read(interfaces: Iterable[HIDInterface], slot: str = "secondary") -> Reading | None:
    for iface in interfaces:
        if iface.usage_page != 0x0006 or iface.usage != 0x0020:
            continue
        with HIDDevice(iface) as dev:
            if iface.feature_len > 0:
                for rid in range(0, 16):
                    r = dev.get_feature(rid)
                    if r and len(r) >= 2 and 0 <= r[1] <= 100:
                        return Reading(
                            slot,
                            "设备",
                            _name_from_product(iface, "HID Battery"),
                            percent=r[1],
                            status=STATUS_OK,
                            detail="标准 HID Battery Strength",
                            source="HID 0x0006/0x0020",
                            raw=bytes(r),
                        )
            if iface.input_len > 0:
                r = dev.read_input(600)
                if r and len(r) >= 2 and 0 <= r[1] <= 100:
                    return Reading(
                        slot,
                        "设备",
                        _name_from_product(iface, "HID Battery"),
                        percent=r[1],
                        status=STATUS_OK,
                        detail="标准 HID Battery Strength",
                        source="HID 0x0006/0x0020",
                        raw=bytes(r),
                    )
    return None


def calibrated_read(interfaces: Iterable[HIDInterface], cfg: dict, slot: str, label: str) -> Reading | None:
    if not cfg:
        return None
    vid = int(cfg.get("vid", -1))
    pid = int(cfg.get("pid", -1))
    iface = find_first(interfaces, vid=vid, pid=pid)
    if iface is None:
        return None
    transport = cfg.get("transport", "feature")
    report_id = int(cfg.get("report_id", 0)) & 0xFF
    offset = max(0, int(cfg.get("offset", 0)))
    scale = str(cfg.get("scale", "raw"))
    with HIDDevice(iface) as dev:
        if transport == "feature":
            raw = dev.get_feature(report_id)
        elif transport == "input":
            raw = dev.read_input(800)
        else:
            raw = dev.read_input(800)
        if not raw or offset >= len(raw):
            return None
        value = raw[offset]
        if scale == "255":
            level = round(value * 100 / 255)
        elif scale == "200":
            level = round(value * 100 / 200)
        else:
            level = value
        level = clamp_percent(level)
        if level is None:
            return None
        return Reading(
            slot,
            label,
            _name_from_product(iface, "手动标定设备"),
            percent=level,
            status=STATUS_OK,
            detail=f"手动标定 offset={offset} scale={scale}",
            source="手动标定",
            raw=bytes(raw),
        )
