"""Current-user Windows DPAPI storage; API credentials never enter the repository."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import tempfile

_PREFIX = b"EMAGKEY1\0"
_MAX_FILE = 64 * 1024
_KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{8,}")


class SecretError(RuntimeError):
    """A deliberately credential-free configuration error."""


def redact(value: object) -> str:
    """Defense in depth for diagnostics; never log request headers or bodies."""
    text = str(value)
    text = _KEY_RE.sub("[API key redacted]", text)
    return re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+",
                  r"\1[redacted]", text)


def _key(value: str) -> str:
    if not isinstance(value, str):
        raise SecretError("API 密钥格式无效。")
    value = value.strip()
    if not 12 <= len(value) <= 512 or not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise SecretError("API 密钥格式无效。")
    return value


def key_path() -> Path:
    directory = os.environ.get("LOCALAPPDATA")
    if not directory:
        raise SecretError("未找到 Windows 本机应用数据目录。请通过 MOONSHOT_API_KEY 环境变量配置。")
    return Path(directory) / "E-musician" / "agent" / "moonshot.key"


def _crypt(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise SecretError("安全密钥文件使用 Windows DPAPI；此平台请使用 MOONSHOT_API_KEY 环境变量。")

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    protect = crypt32.CryptProtectData
    protect.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob),
                        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    protect.restype = wintypes.BOOL
    unprotect = crypt32.CryptUnprotectData
    unprotect.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    unprotect.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    destination = Blob()
    try:
        # CRYPTPROTECT_UI_FORBIDDEN; no LOCAL_MACHINE flag: bound to this Windows user.
        if decrypt:
            ok = unprotect(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination))
        else:
            ok = protect(ctypes.byref(source), "E-musician Moonshot API", None,
                         None, None, 1, ctypes.byref(destination))
        if not ok:
            raise SecretError("Windows 无法解密本机密钥，请重新配置。" if decrypt else
                              "Windows 无法安全保存密钥。")
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        ctypes.memset(buffer, 0, len(data))
        if destination.pbData:
            ctypes.memset(destination.pbData, 0, destination.cbData)
            kernel32.LocalFree(destination.pbData)


def save_key(value: str, *, path: Path | None = None) -> None:
    """Encrypt before touching disk, then atomically replace the encrypted file."""
    value = _key(value)
    encrypted = _PREFIX + _crypt(value.encode("ascii"), decrypt=False)
    destination = path if path is not None else key_path()
    temporary: str | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".moonshot-", suffix=".tmp",
                                         dir=destination.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
    except OSError:
        raise SecretError("无法写入本机加密密钥文件。") from None
    finally:
        if temporary:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass


def load_key(*, path: Path | None = None) -> str:
    """Prefer the persisted current-user key; use environment only if absent."""
    try:
        source = path if path is not None else key_path()
    except SecretError:
        source = None
    if source is not None and source.exists():
        try:
            with source.open("rb") as stream:
                data = stream.read(_MAX_FILE + 1)
            if len(data) > _MAX_FILE or not data.startswith(_PREFIX):
                raise SecretError("本机密钥文件无效，请重新配置。")
            return _key(_crypt(data[len(_PREFIX):], decrypt=True).decode("ascii"))
        except (OSError, UnicodeError):
            raise SecretError("无法读取本机加密密钥，请重新配置。") from None
    value = os.environ.get("MOONSHOT_API_KEY")
    if value:
        return _key(value)
    raise SecretError("尚未配置 Kimi API 密钥。")


def has_key(*, path: Path | None = None) -> bool:
    try:
        load_key(path=path)
        return True
    except SecretError:
        return False
