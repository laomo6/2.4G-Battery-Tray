"""Draw battery-number tray icons with GDI (no Pillow, no image files)."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

DIB_RGB_COLORS = 0
BI_RGB = 0
TRANSPARENT = 1
DT_CENTER = 0x00000001
DT_VCENTER = 0x00000004
DT_SINGLELINE = 0x00000020
DT_NOPREFIX = 0x00000800
FW_BOLD = 700
DEFAULT_CHARSET = 1
OUT_DEFAULT_PRECIS = 0
CLIP_DEFAULT_PRECIS = 0
CLEARTYPE_QUALITY = 5
DEFAULT_PITCH = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", w.DWORD),
        ("biWidth", w.LONG),
        ("biHeight", w.LONG),
        ("biPlanes", w.WORD),
        ("biBitCount", w.WORD),
        ("biCompression", w.DWORD),
        ("biSizeImage", w.DWORD),
        ("biXPelsPerMeter", w.LONG),
        ("biYPelsPerMeter", w.LONG),
        ("biClrUsed", w.DWORD),
        ("biClrImportant", w.DWORD),
    ]


class RGBQUAD(ctypes.Structure):
    _fields_ = [("rgbBlue", ctypes.c_ubyte), ("rgbGreen", ctypes.c_ubyte), ("rgbRed", ctypes.c_ubyte), ("rgbReserved", ctypes.c_ubyte)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", w.BOOL),
        ("xHotspot", w.DWORD),
        ("yHotspot", w.DWORD),
        ("hbmMask", w.HANDLE),
        ("hbmColor", w.HANDLE),
    ]


gdi32.CreateCompatibleDC.argtypes = [w.HDC]
gdi32.CreateCompatibleDC.restype = w.HDC
gdi32.CreateDIBSection.argtypes = [w.HDC, ctypes.POINTER(BITMAPINFO), w.UINT, ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD]
gdi32.CreateDIBSection.restype = w.HANDLE
gdi32.SelectObject.argtypes = [w.HDC, w.HANDLE]
gdi32.SelectObject.restype = w.HANDLE
gdi32.DeleteObject.argtypes = [w.HANDLE]
gdi32.DeleteDC.argtypes = [w.HDC]
gdi32.CreateSolidBrush.argtypes = [w.COLORREF]
gdi32.CreateSolidBrush.restype = w.HANDLE
gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.CreateRoundRectRgn.restype = w.HANDLE
gdi32.FillRgn.argtypes = [w.HDC, w.HANDLE, w.HANDLE]
gdi32.SetBkMode.argtypes = [w.HDC, ctypes.c_int]
gdi32.SetTextColor.argtypes = [w.HDC, w.COLORREF]
gdi32.CreateFontW.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    w.DWORD,
    w.DWORD,
    w.DWORD,
    w.DWORD,
    w.DWORD,
    w.DWORD,
    w.DWORD,
    w.DWORD,
    w.LPCWSTR,
]
gdi32.CreateFontW.restype = w.HANDLE
user32.DrawTextW.argtypes = [w.HDC, w.LPCWSTR, ctypes.c_int, ctypes.POINTER(w.RECT), w.UINT]
user32.DrawTextW.restype = ctypes.c_int
gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, w.UINT, w.UINT, ctypes.c_void_p]
gdi32.CreateBitmap.restype = w.HANDLE
user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
user32.CreateIconIndirect.restype = w.HANDLE
gdi32.PtInRegion.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_int]
gdi32.PtInRegion.restype = w.BOOL
gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.GetStockObject.restype = w.HANDLE
gdi32.Polygon.argtypes = [w.HDC, ctypes.POINTER(w.POINT), ctypes.c_int]
gdi32.Polygon.restype = w.BOOL
gdi32.GetDeviceCaps.argtypes = [w.HDC, ctypes.c_int]
gdi32.GetDeviceCaps.restype = ctypes.c_int
user32.GetDC.argtypes = [w.HWND]
user32.GetDC.restype = w.HDC
user32.ReleaseDC.argtypes = [w.HWND, w.HDC]
user32.DestroyIcon.argtypes = [w.HANDLE]


def _rgb(r: int, g: int, b: int) -> int:
    return r | (g << 8) | (b << 16)


def system_dpi() -> int:
    try:
        fn = user32.GetDpiForSystem
        fn.restype = w.UINT
        dpi = int(fn())
        if 48 <= dpi <= 480:
            return dpi
    except Exception:
        pass
    try:
        hdc = user32.GetDC(None)
        dpi = gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        user32.ReleaseDC(None, hdc)
        if 48 <= dpi <= 480:
            return dpi
    except Exception:
        pass
    return 96


def icon_size() -> int:
    # 32 px at 100%, 48 at 150%, 64 at 200%.  The shell may scale one step.
    size = int(round(16 * system_dpi() / 96 * 2))
    size = max(24, min(72, size))
    return size + (4 - size % 4) % 4


def battery_color(percent: int | None, charging: bool = False, gray: bool = False) -> tuple[int, int, int]:
    if gray or percent is None:
        return (84, 88, 96)
    if percent >= 60:
        return (38, 150, 92)
    if percent >= 30:
        return (198, 158, 38)
    return (192, 57, 43)


def make_icon(percent: int | None, charging: bool = False, gray: bool = False, size: int | None = None):
    size = size or icon_size()
    color = battery_color(percent, charging, gray)
    hdc_screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(hdc_screen)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = size
    bmi.bmiHeader.biHeight = -size
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB
    bits = ctypes.c_void_p()
    dib = gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
    user32.ReleaseDC(None, hdc_screen)
    if not dib or not bits:
        gdi32.DeleteDC(mem)
        return None

    old = gdi32.SelectObject(mem, dib)
    # zero the bitmap (transparent)
    buf = (ctypes.c_ubyte * (size * size * 4)).from_address(bits.value)
    ctypes.memset(buf, 0, len(buf))
    rgn = gdi32.CreateRoundRectRgn(0, 0, size + 1, size + 1, max(6, size // 5), max(6, size // 5))
    brush = gdi32.CreateSolidBrush(_rgb(*color))
    gdi32.FillRgn(mem, rgn, brush)
    gdi32.SetBkMode(mem, TRANSPARENT)
    gdi32.SetTextColor(mem, _rgb(255, 255, 255))

    text = "?" if percent is None else str(max(0, min(100, int(percent))))
    font_h = int(size * (0.62 if len(text) <= 2 else 0.47))
    font = gdi32.CreateFontW(
        -font_h,
        0,
        0,
        0,
        FW_BOLD,
        0,
        0,
        0,
        DEFAULT_CHARSET,
        OUT_DEFAULT_PRECIS,
        CLIP_DEFAULT_PRECIS,
        CLEARTYPE_QUALITY,
        DEFAULT_PITCH,
        "Segoe UI",
    )
    old_font = gdi32.SelectObject(mem, font)
    rect = w.RECT(0, max(0, int(size * 0.03)), size, size)
    user32.DrawTextW(mem, text, -1, ctypes.byref(rect), DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX)
    gdi32.SelectObject(mem, old_font)
    gdi32.DeleteObject(font)

    # GDI does not set alpha.  Set alpha=255 inside the rounded square, 0 outside.
    for y in range(size):
        row = y * size * 4
        for x in range(size):
            idx = row + x * 4
            if gdi32.PtInRegion(rgn, x, y):
                buf[idx + 3] = 255
            else:
                buf[idx] = buf[idx + 1] = buf[idx + 2] = buf[idx + 3] = 0

    mask_bytes = ((size + 15) // 16) * 2 * size
    mask_bits = (ctypes.c_ubyte * mask_bytes)()
    mask = gdi32.CreateBitmap(size, size, 1, 1, mask_bits)
    info = ICONINFO()
    info.fIcon = True
    info.hbmMask = mask
    info.hbmColor = dib
    icon = user32.CreateIconIndirect(ctypes.byref(info))

    gdi32.SelectObject(mem, old)
    gdi32.DeleteObject(brush)
    gdi32.DeleteObject(rgn)
    gdi32.DeleteObject(mask)
    gdi32.DeleteObject(dib)
    gdi32.DeleteDC(mem)
    return icon


def destroy_icon(icon):
    if icon:
        try:
            user32.DestroyIcon(icon)
        except Exception:
            pass


class IconCache:
    """Keep one HICON per (text, color, charging) value."""

    def __init__(self, size: int | None = None):
        self.size = size or icon_size()
        self._cache: dict[tuple, int] = {}

    def get(self, percent: int | None, charging: bool = False, gray: bool = False):
        key = (percent, bool(charging), bool(gray))
        icon = self._cache.get(key)
        if icon is None:
            icon = make_icon(percent, charging, gray, self.size)
            self._cache[key] = icon
        return icon

    def clear(self):
        for icon in self._cache.values():
            destroy_icon(icon)
        self._cache.clear()
