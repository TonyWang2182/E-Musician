"""Loopback-only cloud computation service. Start only after explicit migration."""
from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import sys
import threading
from urllib.parse import urlsplit
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compute.catalog import Catalog
from compute.protocol import MAX_BODY, canonical, validate_request
from compute.store import Conflict, QueueFull, Store
from compute.supervisor import Supervisor


class ComputeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, address, store, catalog):
        self.store, self.catalog = store, catalog
        self.upload_slots = threading.BoundedSemaphore(2)
        self.connection_slots = threading.BoundedSemaphore(32)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.connection_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connection_slots.release()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, *_):
        pass

    def reply(self, status, body=None, headers=None):
        data = b'' if body is None else canonical(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Connection', 'close')
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        self.end_headers(); self.close_connection = True
        if self.command != 'HEAD':
            self.wfile.write(data)

    def content_length(self, maximum):
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
            raise ValueError('Exactly one Content-Length and no Transfer-Encoding are required')
        value = self.headers['Content-Length']
        if not value.isdecimal() or not 0 <= int(value) <= maximum:
            raise ValueError('Invalid Content-Length')
        return int(value)

    def body(self):
        length = self.content_length(MAX_BODY)
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError('Incomplete JSON request')
        return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))

    def dispatch(self):
        if self.headers.get('Origin'):
            return self.reply(403, {'error': 'Browser-origin requests are not supported'})
        path = urlsplit(self.path)
        if path.query or '%' in path.path or '//' in path.path:
            raise ValueError('Unsupported request path')
        parts = path.path.strip('/').split('/')
        store = self.server.store
        if self.command == 'GET' and parts == ['health']:
            return self.reply(200, {'service': 'emusician-compute', 'status': 'ready', 'protocol_version': 2, 'single_heavy_task': True})
        if self.command == 'GET' and parts == ['capabilities']:
            return self.reply(200, self.server.catalog.capabilities())
        if len(parts) == 2 and parts[0] == 'assets':
            if self.command == 'HEAD':
                value = store.asset_info(parts[1])
                return self.reply(200, None, {'X-Content-SHA256': value['sha256'], 'X-Asset-Bytes': value['bytes']})
            if self.command == 'PUT':
                from compute.protocol import MAX_ASSET
                length = self.content_length(MAX_ASSET)
                if not self.server.upload_slots.acquire(blocking=False):
                    return self.reply(429, {'error': 'Two uploads are already in progress'})
                try:
                    return self.reply(200, store.upload(parts[1], length, self.rfile))
                finally:
                    self.server.upload_slots.release()
        if parts == ['jobs'] and self.command == 'POST':
            request = validate_request(self.body())
            # Existing idempotent responses remain readable if the provider is
            # later unavailable; new work requires current deployment readiness.
            try:
                prior = store.get(request['request_id'])
            except KeyError:
                prior = None
            if prior is None and not self.server.catalog.provider(request['model_id'])['available']:
                return self.reply(503, {'error': 'Requested model is unavailable'})
            value, created = store.submit(request)
            return self.reply(202 if created else 200, value)
        if len(parts) >= 2 and parts[0] == 'jobs':
            if len(parts) == 2 and self.command == 'GET':
                return self.reply(200, store.get(parts[1]))
            if len(parts) == 3 and parts[2] == 'cancel' and self.command == 'POST':
                if self.content_length(MAX_BODY):
                    if self.body() not in ({}, None):
                        raise ValueError('Cancellation accepts no parameters')
                return self.reply(200, store.cancel(parts[1]))
            if len(parts) == 4 and parts[2] == 'artifacts' and self.command == 'GET':
                file, item = store.artifact(parts[1], parts[3])
                self.send_response(200); self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(item['bytes'])); self.send_header('X-Content-SHA256', item['sha256'])
                self.send_header('Connection', 'close'); self.end_headers(); self.close_connection = True
                with file.open('rb') as stream:
                    while block := stream.read(1024 * 1024):
                        self.wfile.write(block)
                return
        return self.reply(404, {'error': 'Unknown compute endpoint'})

    def handle_request(self):
        try:
            self.dispatch()
        except KeyError:
            self.reply(404, {'error': 'Task or asset not found'})
        except Conflict as error:
            self.reply(409, {'error': str(error)})
        except QueueFull as error:
            self.reply(429, {'error': str(error)})
        except (ValueError, TypeError, UnicodeError) as error:
            self.reply(400, {'error': str(error)[:400]})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception:
            self.reply(500, {'error': 'Cloud compute service error; inspect the job receipt'})

    do_GET = do_HEAD = do_PUT = do_POST = handle_request


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/root/autodl-tmp/emusician'))
    parser.add_argument('--port', type=int, default=18082)
    args = parser.parse_args()
    root = args.root.resolve(); (root / 'state').mkdir(parents=True, exist_ok=True)
    # Same lock as legacy ACE: start fails safely until the old idle service is
    # explicitly stopped, and its old auto-starter cannot reclaim the GPU later.
    lock = (root / 'state/gateway-service.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    store = Store(root); store.recover(); catalog = Catalog(root)
    service = ComputeHTTPServer(('127.0.0.1', args.port), store, catalog)
    supervisor = Supervisor(store, catalog)
    def shutdown(*_):
        supervisor.shutdown.set()
        threading.Thread(target=service.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown); signal.signal(signal.SIGINT, shutdown)
    (root / 'state/compute.pid').write_text(str(os.getpid()), encoding='ascii')
    supervisor.start()
    try:
        service.serve_forever(poll_interval=.25)
    finally:
        supervisor.close(); service.server_close(); lock.close()


if __name__ == '__main__':
    main()
