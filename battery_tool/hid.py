"""Windows HID access via ctypes only.

No third-party modules.  All handles are opened with ``FILE_FLAG_OVERLAPPED``
where reads/writes are performed so a blocked read can never take the process
down together with a concurrent write (see README "known pits").
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import time
from dataclasses import dataclass
from typing import Iterable

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

HID_GUID_STR = "4d1e55b2-f16f-11cf-88cb-001111000030"
DIGCF_PRESENT = 0x00000002
DIGCF_DEVICEINTERFACE = 0x00000010
OPEN_EXISTING = 3
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_FLAG_OVERLAPPED = 0x40000000
ERROR_IO_PENDING = 997
ERROR_OPERATION_ABORTED = 995
INVALID_HANDLE = ctypes.c_void_p(-1).value
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", w.DWORD),
        ("Data2", w.WORD),
        ("Data3", w.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def guid_from_str(text: str) -> GUID:
    """The last GUID section itself contains dashes; split only three times."""
    parts = text.split("-", 3)
    g = GUID()
    g.Data1 = int(parts[0], 16)
    g.Data2 = int(parts[1], 16)
    g.Data3 = int(parts[2], 16)
    tail = parts[3].replace("-", "")
    for i in range(8):
        g.Data4[i] = int(tail[i * 2 : i * 2 + 2], 16)
    return g


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", w.DWORD),
        ("Reserved", ctypes.c_size_t),
    ]


class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("DevicePath", w.WCHAR * 2048)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Size", w.ULONG),
        ("VendorID", w.USHORT),
        ("ProductID", w.USHORT),
        ("VersionNumber", w.USHORT),
    ]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", w.USHORT),
        ("UsagePage", w.USHORT),
        ("InputReportByteLength", w.USHORT),
        ("OutputReportByteLength", w.USHORT),
        ("FeatureReportByteLength", w.USHORT),
        ("Reserved", w.USHORT * 17),
        ("NumberLinkCollectionNodes", w.USHORT),
        ("NumberInputButtonCaps", w.USHORT),
        ("NumberInputValueCaps", w.USHORT),
        ("NumberInputDataIndices", w.USHORT),
        ("NumberOutputButtonCaps", w.USHORT),
        ("NumberOutputValueCaps", w.USHORT),
        ("NumberOutputDataIndices", w.USHORT),
        ("NumberFeatureButtonCaps", w.USHORT),
        ("NumberFeatureValueCaps", w.USHORT),
        ("NumberFeatureDataIndices", w.USHORT),
    ]


setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), w.LPCWSTR, w.HWND, w.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.POINTER(GUID),
    w.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
]
setupapi.SetupDiEnumDeviceInterfaces.restype = w.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
    ctypes.POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA_W),
    w.DWORD,
    ctypes.POINTER(w.DWORD),
    ctypes.c_void_p,
]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = w.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

hid.HidD_GetAttributes.argtypes = [w.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetAttributes.restype = w.BOOL
hid.HidD_GetPreparsedData.argtypes = [w.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_GetPreparsedData.restype = w.BOOL
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid.HidP_GetCaps.restype = w.LONG
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidD_GetProductString.argtypes = [w.HANDLE, ctypes.c_wchar_p, w.ULONG]
hid.HidD_GetManufacturerString.argtypes = [w.HANDLE, ctypes.c_wchar_p, w.ULONG]
hid.HidD_GetSerialNumberString.argtypes = [w.HANDLE, ctypes.c_wchar_p, w.ULONG]
hid.HidD_GetFeature.argtypes = [w.HANDLE, ctypes.c_void_p, w.ULONG]
hid.HidD_GetFeature.restype = w.BOOL
hid.HidD_SetFeature.argtypes = [w.HANDLE, ctypes.c_void_p, w.ULONG]
hid.HidD_SetFeature.restype = w.BOOL
hid.HidD_SetOutputReport.argtypes = [w.HANDLE, ctypes.c_void_p, w.ULONG]
hid.HidD_SetOutputReport.restype = w.BOOL
hid.HidD_SetNumInputBuffers.argtypes = [w.HANDLE, w.ULONG]
hid.HidD_SetNumInputBuffers.restype = w.BOOL

kernel32.CreateFileW.restype = w.HANDLE
kernel32.CreateFileW.argtypes = [
    w.LPCWSTR,
    w.DWORD,
    w.DWORD,
    ctypes.c_void_p,
    w.DWORD,
    w.DWORD,
    w.HANDLE,
]
kernel32.CloseHandle.argtypes = [w.HANDLE]
kernel32.CreateEventW.restype = w.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR]
kernel32.ResetEvent.argtypes = [w.HANDLE]
kernel32.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
kernel32.ReadFile.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
kernel32.WriteFile.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
kernel32.CancelIoEx.argtypes = [w.HANDLE, ctypes.c_void_p]
kernel32.GetOverlappedResult.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.POINTER(w.DWORD), w.BOOL]
kernel32.GetOverlappedResult.restype = w.BOOL


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", w.DWORD),
        ("OffsetHigh", w.DWORD),
        ("hEvent", w.HANDLE),
    ]


def _invalid(h) -> bool:
    return h in (None, 0, INVALID_HANDLE)


def _open(path: str, access: int, overlapped: bool = False):
    flags = FILE_FLAG_OVERLAPPED if overlapped else 0
    return kernel32.CreateFileW(path, access, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, flags, None)


def _hid_string(fn, h) -> str:
    buf = ctypes.create_unicode_buffer(256)
    try:
        if fn(h, buf, ctypes.sizeof(buf)):
            return buf.value
    except Exception:
        pass
    return ""


@dataclass(frozen=True)
class HIDInterface:
    path: str
    vid: int
    pid: int
    version: int
    usage_page: int
    usage: int
    input_len: int
    output_len: int
    feature_len: int
    product: str
    manufacturer: str
    serial: str

    @property
    def vidpid(self) -> str:
        return f"{self.vid:04X}:{self.pid:04X}"

    @property
    def label(self) -> str:
        return self.product or self.manufacturer or self.vidpid


def enumerate_hid() -> list[HIDInterface]:
    """Enumerate every present HID interface (one entry per top-level collection)."""
    g = guid_from_str(HID_GUID_STR)
    hdev = setupapi.SetupDiGetClassDevsW(ctypes.byref(g), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if not hdev or hdev == INVALID_HANDLE:
        return []
    result: list[HIDInterface] = []
    idx = 0
    try:
        while True:
            did = SP_DEVICE_INTERFACE_DATA()
            did.cbSize = ctypes.sizeof(did)
            if not setupapi.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(g), idx, ctypes.byref(did)):
                break
            idx += 1
            detail = SP_DEVICE_INTERFACE_DETAIL_DATA_W()
            detail.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            req = w.DWORD()
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, ctypes.byref(did), ctypes.byref(detail), ctypes.sizeof(detail), ctypes.byref(req), None
            ):
                continue
            path = detail.DevicePath
            h = _open(path, 0)
            if _invalid(h):
                continue
            try:
                attrs = HIDD_ATTRIBUTES()
                attrs.Size = ctypes.sizeof(attrs)
                if not hid.HidD_GetAttributes(h, ctypes.byref(attrs)):
                    continue
                prep = ctypes.c_void_p()
                if not hid.HidD_GetPreparsedData(h, ctypes.byref(prep)):
                    continue
                try:
                    caps = HIDP_CAPS()
                    hid.HidP_GetCaps(prep, ctypes.byref(caps))
                finally:
                    hid.HidD_FreePreparsedData(prep)
                result.append(
                    HIDInterface(
                        path=path,
                        vid=attrs.VendorID,
                        pid=attrs.ProductID,
                        version=attrs.VersionNumber,
                        usage_page=caps.UsagePage,
                        usage=caps.Usage,
                        input_len=caps.InputReportByteLength,
                        output_len=caps.OutputReportByteLength,
                        feature_len=caps.FeatureReportByteLength,
                        product=_hid_string(hid.HidD_GetProductString, h),
                        manufacturer=_hid_string(hid.HidD_GetManufacturerString, h),
                        serial=_hid_string(hid.HidD_GetSerialNumberString, h),
                    )
                )
            finally:
                kernel32.CloseHandle(h)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev)
    # Stable order: mouse first, vendor collections next.
    result.sort(key=lambda i: (i.vid, i.pid, i.usage_page, i.usage, i.path))
    return result


class HIDDevice:
    """Safe, reusable handle bundle for one HID collection."""

    def __init__(self, iface: HIDInterface):
        self.iface = iface
        self._feature = None
        self._rw = None
        self._read = None
        self._read_event = None
        self._write_lock_owner = None

    # -- handles ---------------------------------------------------------
    def _ensure_feature(self):
        if self._feature is None or _invalid(self._feature):
            self._feature = _open(self.iface.path, 0)
        return self._feature

    def _ensure_rw(self):
        if self._rw is None:
            self._rw = _open(self.iface.path, GENERIC_READ | GENERIC_WRITE)
        return self._rw

    def _ensure_read(self):
        if self._read is None or _invalid(self._read):
            self._read = _open(self.iface.path, GENERIC_READ, overlapped=True)
            if _invalid(self._read):
                self._read = None
                return None
            try:
                hid.HidD_SetNumInputBuffers(self._read, 64)
            except Exception:
                pass
        if self._read_event is None or _invalid(self._read_event):
            self._read_event = kernel32.CreateEventW(None, True, False, None)
        return self._read

    # -- reports ---------------------------------------------------------
    def get_feature(self, report_id: int, length: int | None = None) -> bytes | None:
        h = self._ensure_feature()
        if _invalid(h):
            return None
        n = length or self.iface.feature_len
        if n <= 0:
            return None
        buf = (ctypes.c_ubyte * n)()
        buf[0] = report_id & 0xFF
        if not hid.HidD_GetFeature(h, buf, n):
            return None
        return bytes(buf)

    def set_feature(self, data: bytes, length: int | None = None) -> bool:
        h = self._ensure_feature()
        if _invalid(h):
            return False
        n = length or self.iface.feature_len
        if n <= 0:
            return False
        buf = (ctypes.c_ubyte * n)()
        raw = data[:n]
        for i, b in enumerate(raw):
            buf[i] = b
        return bool(hid.HidD_SetFeature(h, buf, n))

    def _write_overlapped(self, h, data: bytes, timeout_ms: int) -> bool:
        ev = kernel32.CreateEventW(None, True, False, None)
        ov = OVERLAPPED()
        ov.hEvent = ev
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        n = w.DWORD()
        try:
            kernel32.ResetEvent(ev)
            ok = kernel32.WriteFile(h, buf, len(data), ctypes.byref(n), ctypes.byref(ov))
            err = ctypes.get_last_error()
            if not ok and err != ERROR_IO_PENDING:
                return False
            if not ok:
                if kernel32.WaitForSingleObject(ev, timeout_ms) != WAIT_OBJECT_0:
                    kernel32.CancelIoEx(h, ctypes.byref(ov))
                    kernel32.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(n), True)
                    return False
                if not kernel32.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(n), False):
                    return False
            return True
        finally:
            kernel32.CloseHandle(ev)

    def write_output(self, data: bytes, timeout_ms: int = 800) -> bool:
        if self.iface.output_len <= 0:
            return False
        n = self.iface.output_len
        raw = (data + bytes(n))[:n]
        h = self._ensure_rw()
        if not _invalid(h):
            return self._write_overlapped(h, raw, timeout_ms)
        # Feature-only collections may still accept an output report.
        hf = self._ensure_feature()
        if _invalid(hf):
            return False
        buf = (ctypes.c_ubyte * n).from_buffer_copy(raw)
        return bool(hid.HidD_SetOutputReport(hf, buf, n))

    def read_input(self, timeout_ms: int = 700, length: int | None = None) -> bytes | None:
        h = self._ensure_read()
        ev = self._read_event
        if _invalid(h) or _invalid(ev):
            return None
        n = length or self.iface.input_len
        if n <= 0:
            return None
        buf = (ctypes.c_ubyte * n)()
        ov = OVERLAPPED()
        ov.hEvent = ev
        got = w.DWORD()
        try:
            kernel32.ResetEvent(ev)
            ok = kernel32.ReadFile(h, buf, n, ctypes.byref(got), ctypes.byref(ov))
            err = ctypes.get_last_error()
            if not ok and err != ERROR_IO_PENDING:
                return None
            if not ok:
                wait = kernel32.WaitForSingleObject(ev, max(1, timeout_ms))
                if wait != WAIT_OBJECT_0:
                    kernel32.CancelIoEx(h, ctypes.byref(ov))
                    kernel32.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(got), True)
                    return None
                if not kernel32.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(got), False):
                    return None
            if got.value <= 0:
                return None
            return bytes(buf[: got.value])
        finally:
            pass

    def read_for(self, seconds: float, max_reports: int = 200) -> list[bytes]:
        deadline = time.monotonic() + seconds
        out: list[bytes] = []
        while time.monotonic() < deadline and len(out) < max_reports:
            left = max(0.05, min(0.25, deadline - time.monotonic()))
            r = self.read_input(int(left * 1000))
            if r:
                out.append(r)
        return out

    def close(self):
        if self._read is not None and not _invalid(self._read):
            try:
                kernel32.CancelIoEx(self._read, None)
            except Exception:
                pass
        for name in ("_read", "_feature", "_rw"):
            h = getattr(self, name)
            if h is not None and not _invalid(h):
                kernel32.CloseHandle(h)
            setattr(self, name, None)
        if self._read_event is not None and not _invalid(self._read_event):
            kernel32.CloseHandle(self._read_event)
        self._read_event = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def find_first(
    interfaces: Iterable[HIDInterface],
    *,
    vid: int | None = None,
    pid: int | None = None,
    usage_page: int | None = None,
    usage: int | None = None,
    min_input: int = 0,
    min_output: int = 0,
    exact_input: int | None = None,
    exact_output: int | None = None,
    feature: int | None = None,
) -> HIDInterface | None:
    for i in interfaces:
        if vid is not None and i.vid != vid:
            continue
        if pid is not None and i.pid != pid:
            continue
        if usage_page is not None and i.usage_page != usage_page:
            continue
        if usage is not None and i.usage != usage:
            continue
        if exact_input is not None and i.input_len != exact_input:
            continue
        if exact_output is not None and i.output_len != exact_output:
            continue
        if i.input_len < min_input or i.output_len < min_output:
            continue
        if feature is not None and i.feature_len != feature:
            continue
        return i
    return None


def hexs(data: bytes, limit: int | None = None) -> str:
    raw = data if limit is None else data[:limit]
    return " ".join(f"{b:02X}" for b in raw)
