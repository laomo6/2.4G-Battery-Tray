"""Startup shortcut (.lnk) and desktop links.

The .lnk is created with raw ctypes COM: CoCreateInstance(CLSID_ShellLink) ->
IShellLinkW -> QueryInterface(IPersistFile) -> Save.  No pywin32.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os
import subprocess
import sys
import winreg
from pathlib import Path

ole32 = ctypes.WinDLL("ole32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

CLSCTX_INPROC_SERVER = 1
COINIT_APARTMENTTHREADED = 2
CSIDL_DESKTOPDIRECTORY = 0x0010
CREATE_NO_WINDOW = 0x08000000
HRESULT = ctypes.c_long


class GUID(ctypes.Structure):
    _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _guid(text: str) -> GUID:
    parts = text.split("-", 3)
    g = GUID()
    g.Data1 = int(parts[0], 16)
    g.Data2 = int(parts[1], 16)
    g.Data3 = int(parts[2], 16)
    tail = parts[3].replace("-", "")
    for i in range(8):
        g.Data4[i] = int(tail[i * 2 : i * 2 + 2], 16)
    return g


CLSID_ShellLink = _guid("00021401-0000-0000-C000-000000000046")
IID_IShellLinkW = _guid("000214F9-0000-0000-C000-000000000046")
IID_IPersistFile = _guid("0000010B-0000-0000-C000-000000000046")

ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, w.DWORD]
ole32.CoInitializeEx.restype = HRESULT
ole32.CoUninitialize.argtypes = []
ole32.CoCreateInstance.argtypes = [
    ctypes.POINTER(GUID),
    ctypes.c_void_p,
    w.DWORD,
    ctypes.POINTER(GUID),
    ctypes.POINTER(ctypes.c_void_p),
]
ole32.CoCreateInstance.restype = HRESULT
shell32.SHGetFolderPathW.argtypes = [w.HWND, ctypes.c_int, w.HANDLE, w.DWORD, w.LPWSTR]
shell32.SHGetFolderPathW.restype = HRESULT


def _addr(ptr) -> int:
    return int(ptr.value) if isinstance(ptr, ctypes.c_void_p) else int(ptr)


def _vtbl(ptr, index, restype, *argtypes):
    # object -> vtable pointer -> function table
    vtable_ptr = ctypes.cast(_addr(ptr), ctypes.POINTER(ctypes.c_void_p))[0]
    table = ctypes.cast(vtable_ptr, ctypes.POINTER(ctypes.c_void_p))
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(table[index])


def _release(ptr):
    if ptr:
        try:
            _vtbl(ptr, 2, ctypes.c_ulong)(ptr)
        except Exception:
            pass


def _query_interface(ptr, iid: GUID):
    out = ctypes.c_void_p()
    fn = _vtbl(ptr, 0, HRESULT, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
    hr = fn(ptr, ctypes.byref(iid), ctypes.byref(out))
    if hr < 0:
        return None
    return out


def create_shortcut(
    link_path: Path,
    target: Path,
    arguments: str,
    working_dir: Path,
    description: str,
    icon: Path | None = None,
) -> bool:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    try:
        psl = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_ShellLink), None, CLSCTX_INPROC_SERVER, ctypes.byref(IID_IShellLinkW), ctypes.byref(psl)
        )
        if hr < 0 or not psl:
            return False
        try:
            _vtbl(psl, 20, HRESULT, w.LPCWSTR)(psl, str(target))
            _vtbl(psl, 11, HRESULT, w.LPCWSTR)(psl, arguments)
            _vtbl(psl, 9, HRESULT, w.LPCWSTR)(psl, str(working_dir))
            _vtbl(psl, 7, HRESULT, w.LPCWSTR)(psl, description)
            if icon:
                _vtbl(psl, 17, HRESULT, w.LPCWSTR, ctypes.c_int)(psl, str(icon), 0)
            pf = _query_interface(psl, IID_IPersistFile)
            if not pf:
                return False
            try:
                _vtbl(pf, 6, HRESULT, w.LPCWSTR, w.BOOL)(pf, str(link_path), True)
            finally:
                _release(pf)
        finally:
            _release(psl)
        return link_path.exists()
    finally:
        try:
            ole32.CoUninitialize()
        except Exception:
            pass


def read_shortcut(link_path: Path) -> dict | None:
    if not link_path.exists():
        return None
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    try:
        psl = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_ShellLink), None, CLSCTX_INPROC_SERVER, ctypes.byref(IID_IShellLinkW), ctypes.byref(psl)
        )
        if hr < 0 or not psl:
            return None
        try:
            pf = _query_interface(psl, IID_IPersistFile)
            if not pf:
                return None
            try:
                hr = _vtbl(pf, 5, HRESULT, w.LPCWSTR, w.DWORD)(pf, str(link_path), 0)
                if hr < 0:
                    return None
            finally:
                _release(pf)
            target_buf = ctypes.create_unicode_buffer(1024)
            args_buf = ctypes.create_unicode_buffer(1024)
            work_buf = ctypes.create_unicode_buffer(1024)
            _vtbl(psl, 3, HRESULT, w.LPWSTR, ctypes.c_int, ctypes.c_void_p, w.DWORD)(
                psl, target_buf, 1024, None, 0
            )
            _vtbl(psl, 10, HRESULT, w.LPWSTR, ctypes.c_int)(psl, args_buf, 1024)
            _vtbl(psl, 8, HRESULT, w.LPWSTR, ctypes.c_int)(psl, work_buf, 1024)
            return {"target": target_buf.value, "arguments": args_buf.value, "working_dir": work_buf.value}
        finally:
            _release(psl)
    finally:
        try:
            ole32.CoUninitialize()
        except Exception:
            pass


def project_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def pythonw() -> Path:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    if candidate.exists():
        return candidate
    return exe


def startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path:
    return startup_dir() / "电量托盘.lnk"


APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"


def _approved_value() -> bytes | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, shortcut_path().name)
            if isinstance(value, bytes):
                return value
    except OSError:
        pass
    return None


def _set_approved(enabled: bool):
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as key:
            # Task Manager's StartupApproved binary: first DWORD 2=enabled,
            # 3=disabled, followed by zeros.
            status = 2 if enabled else 3
            winreg.SetValueEx(key, shortcut_path().name, 0, winreg.REG_BINARY, bytes([status]) + bytes(11))
    except OSError:
        pass


def _delete_approved():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, shortcut_path().name)
    except OSError:
        pass


def desktop_dir() -> Path:
    buf = ctypes.create_unicode_buffer(1024)
    try:
        hr = shell32.SHGetFolderPathW(None, CSIDL_DESKTOPDIRECTORY, None, 0, buf)
        if hr >= 0 and buf.value:
            return Path(buf.value)
    except Exception:
        pass
    return Path.home() / "Desktop"


def ensure_launchers() -> tuple[Path, Path]:
    """Create tiny launcher scripts.  The desktop link points at the .vbs one."""
    base = project_dir()
    pyw = pythonw()
    script = base / "my_devices.py"
    bat = base / "启动.bat"
    vbs = base / "启动.vbs"
    try:
        bat.write_text(
            '@echo off\r\nstart "" "' + str(pyw) + '" "' + str(script) + '" %*\r\n',
            encoding="gbk",
            errors="replace",
        )
    except Exception:
        pass
    try:
        vbs.write_text(
            'Set sh = CreateObject("WScript.Shell")\r\n'
            'sh.Run """" & "' + str(pyw) + '" & """ """ & "' + str(script) + '" & """", 0, False\r\n',
            encoding="utf-16",
        )
    except Exception:
        pass
    return bat, vbs


def autostart_enabled() -> bool:
    if not shortcut_path().exists():
        return False
    value = _approved_value()
    if value and len(value) >= 1 and value[0] == 3:
        return False
    return True


def autostart_info() -> dict | None:
    info = read_shortcut(shortcut_path())
    if info is not None:
        info["enabled"] = autostart_enabled()
        approved = _approved_value()
        info["startup_approved"] = approved.hex() if approved else ""
    return info


def install_autostart() -> tuple[bool, str]:
    ensure_launchers()
    path = shortcut_path()
    info = read_shortcut(path)
    expected_target = str(pythonw())
    expected_args = f'"{project_dir() / "my_devices.py"}" --tray'
    if info and info.get("target", "").lower() == expected_target.lower() and info.get("arguments", "") == expected_args:
        _set_approved(True)
        return True, f"启动项已存在：{path.name}（已启用）"
    if info and info.get("target"):
        return False, f"启动项已存在但指向其他目标，未修改：{info.get('target')}"
    ok = create_shortcut(
        path,
        pythonw(),
        expected_args,
        project_dir(),
        "2.4G 无线外设电量托盘",
        pythonw(),
    )
    if ok:
        _set_approved(True)
    return ok, ("已创建启动项：" + str(path)) if ok else "创建启动项失败"


def remove_autostart() -> tuple[bool, str]:
    path = shortcut_path()
    if not path.exists():
        _delete_approved()
        return True, "启动项不存在"
    info = read_shortcut(path)
    if info and info.get("target"):
        target = info.get("target", "").lower()
        args = info.get("arguments", "")
        if "my_devices.py" not in args and target not in (
            str(pythonw()).lower(),
            str(Path(sys.executable)).lower(),
        ):
            return False, "启动项不是本工具创建的，未删除"
    try:
        path.unlink()
        _delete_approved()
        return True, "已删除启动项"
    except Exception as exc:
        return False, f"删除启动项失败：{exc}"


def _remove_link(path: Path) -> bool:
    try:
        if path.is_symlink():
            path.unlink()
            return True
        if path.is_dir():
            os.rmdir(path)  # junction
            return True
        path.unlink()
        return True
    except Exception:
        return False


def _try_symlink(target: Path, link: Path, is_dir: bool) -> bool:
    """Try Python's symlink, then CreateSymbolicLinkW with the unprivileged flag."""
    try:
        os.symlink(str(target), str(link), target_is_directory=is_dir)
        return True
    except OSError:
        pass
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateSymbolicLinkW.argtypes = [w.LPCWSTR, w.LPCWSTR, w.DWORD]
        # CreateSymbolicLinkW returns BOOLEAN (one byte), not BOOL.
        k32.CreateSymbolicLinkW.restype = ctypes.c_ubyte
        flags = 0x2 | (0x1 if is_dir else 0)  # ALLOW_UNPRIVILEGED_CREATE | DIRECTORY
        return k32.CreateSymbolicLinkW(str(link), str(target), flags) == 1
    except Exception:
        return False


def _same_target(link: Path, target: Path) -> bool:
    try:
        if link.is_symlink():
            return Path(os.path.realpath(link)) == target.resolve()
        if link.is_dir():
            return Path(os.path.realpath(link)) == target.resolve()
        return link.stat().st_ino == target.stat().st_ino and link.stat().st_dev == target.stat().st_dev
    except Exception:
        return False


def install_desktop() -> list[str]:
    messages: list[str] = []
    desktop = desktop_dir()
    base = project_dir()
    bat, vbs = ensure_launchers()

    dir_link = desktop / "2.4G电量"
    if dir_link.exists():
        if _same_target(dir_link, base):
            messages.append(f"目录链接已存在：{dir_link.name}")
        else:
            messages.append(f"桌面已有同名项目，未覆盖：{dir_link}")
    else:
        ok = False
        if _try_symlink(base, dir_link, True):
            ok = True
            messages.append(f"已创建目录符号链接：{dir_link.name}")
        else:
            try:
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(dir_link), str(base)],
                    capture_output=True,
                    text=True,
                    creationflags=CREATE_NO_WINDOW,
                )
                ok = result.returncode == 0 and dir_link.exists()
                if ok:
                    messages.append(f"已创建目录 junction：{dir_link.name}")
            except Exception:
                ok = False
        if not ok:
            messages.append("目录链接创建失败（需要管理员/开发者模式或 junction 支持）")

    file_link = desktop / "启动 2.4G 电量.vbs"
    if file_link.exists():
        if _same_target(file_link, vbs):
            messages.append(f"启动文件链接已存在：{file_link.name}")
        else:
            messages.append(f"桌面已有同名启动文件，未覆盖：{file_link}")
    else:
        ok = False
        if _try_symlink(vbs, file_link, False):
            ok = True
            messages.append(f"已创建文件符号链接：{file_link.name}")
        else:
            try:
                os.link(str(vbs), str(file_link))
                ok = True
                messages.append(f"已创建文件硬链接：{file_link.name}")
            except OSError:
                ok = False
        if not ok:
            # Cross-volume desktop: a .lnk to the same startup script is still
            # a link, never a copy of the script.
            fallback = desktop / "启动 2.4G 电量.lnk"
            existing = read_shortcut(fallback)
            if existing and existing.get("target", "").lower().endswith("启动.vbs"):
                messages.append(f"启动快捷方式已存在：{fallback.name}")
            elif create_shortcut(
                fallback,
                vbs,
                "",
                base,
                "启动 2.4G 电量",
                pythonw(),
            ):
                messages.append(f"文件链接不可用，已改用快捷方式：{fallback.name}")
            else:
                messages.append("启动文件链接创建失败")

    # If the real file link exists, remove the older fallback .lnk so the
    # desktop has exactly one launch entry.
    fallback = desktop / "启动 2.4G 电量.lnk"
    if file_link.exists() and fallback.exists():
        info = read_shortcut(fallback)
        if info and (
            info.get("target", "").lower().endswith("启动.vbs")
            or "my_devices.py" in info.get("arguments", "")
        ):
            try:
                fallback.unlink()
                messages.append("已移除旧的启动快捷方式")
            except OSError:
                pass
    return messages


def uninstall_desktop() -> list[str]:
    messages: list[str] = []
    desktop = desktop_dir()
    base = project_dir()
    dir_link = desktop / "2.4G电量"
    if dir_link.exists():
        if _same_target(dir_link, base):
            if _remove_link(dir_link):
                messages.append("已删除桌面目录链接")
            else:
                messages.append("删除桌面目录链接失败")
        else:
            messages.append("桌面同名目录不是本项目的链接，未删除")
    for name in ("启动 2.4G 电量.vbs", "启动 2.4G 电量.lnk"):
        path = desktop / name
        if path.exists():
            if _remove_link(path):
                messages.append(f"已删除桌面链接：{name}")
            else:
                messages.append(f"删除桌面链接失败：{name}")
    return messages


def install_all() -> list[str]:
    messages: list[str] = []
    ok, msg = install_autostart()
    messages.append(msg)
    messages.extend(install_desktop())
    return messages


def uninstall_all() -> list[str]:
    messages: list[str] = []
    ok, msg = remove_autostart()
    messages.append(msg)
    messages.extend(uninstall_desktop())
    return messages
