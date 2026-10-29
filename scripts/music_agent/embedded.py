"""Authenticated loopback client for a DAW-owned helper; never launches/closes the DAW."""
from __future__ import annotations
import json
import math
from pathlib import Path
import re
import select
import socket
import threading
from agent_client import ControlError

MAX_BYTES = 1024 * 1024


def _object(payload):
    text = payload.decode("utf-8-sig")
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 64:
                raise ValueError("Embedded JSON nesting limit exceeded.")
        elif char in "]}":
            depth -= 1

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate embedded JSON field.")
            result[key] = value
        return result

    def reject(_):
        raise ValueError("Non-finite embedded JSON number.")

    def number(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("Non-finite embedded JSON number.")
        return value

    value = json.loads(text, object_pairs_hook=unique,
                       parse_constant=reject, parse_float=number)
    if not isinstance(value, dict):
        raise ValueError("Expected embedded JSON object.")
    return value


def load_session(path):
    path = Path(path).resolve()
    with path.open("rb") as source:
        payload = source.read(4097)
    if not payload or len(payload) > 4096:
        raise ValueError("Invalid embedded session size.")
    value = _object(payload)
    if set(value) != {"protocol", "port", "token", "ready_path"} or type(value["protocol"]) is not int or value["protocol"] != 1:
        raise ValueError("Unsupported embedded protocol.")
    if type(value["port"]) is not int or not 1 <= value["port"] <= 65535:
        raise ValueError("Invalid embedded endpoint.")
    if not isinstance(value["token"],str) or not re.fullmatch(r"[0-9a-fA-F]{64}",value["token"]):
        raise ValueError("Invalid embedded capability.")
    if not isinstance(value["ready_path"], str) or not value["ready_path"]:
        raise ValueError("Invalid embedded readiness path.")
    ready = Path(value["ready_path"]).resolve()
    if ready.parent != path.parent or ready.name != path.stem + ".ready.json":
        raise ValueError("Invalid embedded readiness path.")
    return value

class SocketClient:
    def __init__(self, session, *, timeout=20):
        self.lock = threading.Lock()
        self.embedded = True
        self.socket = None
        self.stream = None
        self.closed = True
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Invalid embedded connection timeout.")
        try:
            self.socket = socket.create_connection(("127.0.0.1", session["port"]), timeout=timeout)
            self.socket.settimeout(timeout)
            self.stream = self.socket.makefile("rb")
            self.closed = False
            result = self.raw({"auth":session["token"]})
            if result != {"status":"authenticated"}:
                raise ControlError("Embedded DAW authentication failed.")
        except OSError as exc:
            self.close()
            raise ControlError("Embedded DAW connection failed.") from exc
        except Exception:
            self.close()
            raise
    def raw(self, request):
        with self.lock:
            if self.closed:
                raise ControlError("Embedded DAW disconnected.")
            try:
                encoded=(json.dumps(request,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n").encode("utf-8")
            except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
                raise ControlError("Invalid embedded request JSON.") from exc
            if len(encoded)>MAX_BYTES:
                raise ControlError("Embedded request size exceeded.")
            try:
                connection, stream = self.socket, self.stream
                if connection is None or stream is None:
                    raise ControlError("Embedded DAW disconnected.")
                connection.sendall(encoded)
                line=stream.readline(MAX_BYTES+1)
                if not line.endswith(b"\n") or len(line)>MAX_BYTES:
                    raise ControlError("Embedded DAW reply incomplete or oversized.")
                return _object(line)
            except (ControlError, OSError, UnicodeError, ValueError, RecursionError) as exc:
                # A late response could belong to a previous mutation. Poison
                # the entire stream; no caller may reuse it after ambiguity.
                self.close()
                raise ControlError("Embedded DAW request failed; no automatic retry.") from exc

    def is_alive(self):
        """Peek for idle EOF without consuming a reply or waiting on an RPC.

        A request currently owns the reader and its timeout. The watchdog must
        leave that request alone; its eventual failure will poison the stream.
        """
        if self.closed:
            return False
        if not self.lock.acquire(blocking=False):
            return not self.closed
        try:
            connection = self.socket
            if self.closed or connection is None:
                return False
            readable, _, exceptional = select.select([connection], [], [connection], 0)
            if exceptional or (readable and connection.recv(1, socket.MSG_PEEK) == b""):
                self.close()
                return False
            return True
        except (OSError, ValueError):
            self.close()
            return False
        finally:
            self.lock.release()

    def close(self):
        self.closed = True
        connection, stream = self.socket, self.stream
        self.socket = self.stream = None
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
        if connection is not None:
            connection.close()
