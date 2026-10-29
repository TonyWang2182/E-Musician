"""Current-user Windows DPAPI storage; API credentials never enter the repository."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import tempfile
import json
import threading

_PREFIX = b"EMAGKEY1\0"
_PREFIX_V2 = b"EMAGKEY2\0"
_NAMESPACES = {"kimi": ("moonshot.key", "MOONSHOT_API_KEY"),
               "openai": ("openai.key", "OPENAI_API_KEY"),
               "anthropic": ("anthropic.key", "ANTHROPIC_API_KEY"),
               "gemini": ("gemini.key", "GEMINI_API_KEY"),
               "local-compatible": ("local-compatible.key", "LOCAL_LLM_API_KEY")}
_KNOWN_KEYS = set()
_KEY_LOCK = threading.Lock()
_MAX_FILE = 64 * 1024
_KEY_RE = re.compile(r"sk-[A-Za-z0-9_.-]{8,}")


class SecretError(RuntimeError):
    """A deliberately credential-free configuration error."""


def redact(value: object) -> str:
    """Defense in depth for diagnostics; never log request headers or bodies."""
    text = str(value)
    with _KEY_LOCK:
        known = sorted(_KNOWN_KEYS, key=len, reverse=True)
    for key in known:
        text = text.replace(key, "[API key redacted]")
    text = _KEY_RE.sub("[API key redacted]", text)
    return re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+",
                  r"\1[redacted]", text)


def _key(value: str) -> str:
    if not isinstance(value, str):
        raise SecretError("API 密钥格式无效。")
    value = value.strip()
    if not 12 <= len(value) <= 4096 or not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise SecretError("API 密钥格式无效。")
    return value


def _remember(value: str) -> str:
    with _KEY_LOCK:
        if len(_KNOWN_KEYS) < 64:
            _KNOWN_KEYS.add(value)
    return value


def _namespace(provider):
    if provider not in _NAMESPACES:
        raise SecretError("未知模型服务，未访问任何凭证。")
    return _NAMESPACES[provider]


def key_path(provider: str = "kimi") -> Path:
    filename, _ = _namespace(provider)
    directory = os.environ.get("LOCALAPPDATA")
    if not directory:
        raise SecretError("未找到 Windows 本机应用数据目录。请通过对应服务的环境变量配置。")
    return Path(directory) / "E-musician" / "agent" / filename


def _crypt(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise SecretError("安全密钥文件使用 Windows DPAPI；此平台请使用对应服务的环境变量。")

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
            ok = protect(ctypes.byref(source), "E-musician provider API", None,
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


def save_key(value: str, *, provider: str = "kimi", path: Path | None = None) -> None:
    """Bind the encrypted plaintext to its provider; preserve legacy Moonshot path."""
    _namespace(provider)
    value = _remember(_key(value))
    payload = json.dumps({"provider": provider, "key": value}, separators=(",", ":")).encode("ascii")
    encrypted = _PREFIX_V2 + _crypt(payload, decrypt=False)
    destination = Path(path) if path is not None else key_path(provider)
    temporary: str | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".credential-", suffix=".tmp",
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


def load_key(*, provider: str = "kimi", path: Path | None = None) -> str:
    """Never fall back to another provider's file or environment variable."""
    _, environment = _namespace(provider)
    try:
        source = Path(path) if path is not None else key_path(provider)
    except SecretError:
        source = None
    try:
        exists = source is not None and source.exists()
    except OSError:
        raise SecretError("无法读取本机凭证目录。") from None
    if exists:
        try:
            with source.open("rb") as stream:
                data = stream.read(_MAX_FILE + 1)
            if len(data) > _MAX_FILE:
                raise SecretError("本机密钥文件无效，请重新配置。")
            if data.startswith(_PREFIX_V2):
                value = json.loads(_crypt(data[len(_PREFIX_V2):], decrypt=True).decode("ascii"))
                if not isinstance(value, dict) or set(value) != {"provider", "key"} or value["provider"] != provider:
                    raise SecretError("密钥所属服务不匹配，请为当前服务配置独立密钥。")
                return _remember(_key(value["key"]))
            if provider == "kimi" and data.startswith(_PREFIX):
                return _remember(_key(_crypt(data[len(_PREFIX):], decrypt=True).decode("ascii")))
            raise SecretError("本机密钥文件无效，请重新配置。")
        except (OSError, UnicodeError, ValueError):
            raise SecretError("无法读取本机加密密钥，请重新配置。") from None
    value = os.environ.get(environment)
    if value:
        return _remember(_key(value))
    raise SecretError("尚未配置当前服务的 API 密钥。")


def has_key(*, provider: str = "kimi", path: Path | None = None) -> bool:
    try:
        load_key(provider=provider, path=path)
        return True
    except SecretError:
        return False
