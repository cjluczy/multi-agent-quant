#!/usr/bin/env python
"""Run a local control console for the multi-agent quant MVP."""
from __future__ import annotations

import argparse
import json
import pathlib
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from multi_agent_quant.console.service import ConsoleService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the local control console")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind")
    parser.add_argument(
        "--config",
        default="configs/system.example.yaml",
        help="Base config used by the console",
    )
    return parser.parse_args()


def make_handler(service: ConsoleService):
    class ControlConsoleHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT), **kwargs)

        def do_GET(self) -> None:  # noqa: N802
            route_path = urlparse(self.path).path
            if route_path in {
                "/",
                "/console",
                "/console/",
                "/console/overview",
                "/console/run",
                "/console/agents",
                "/console/agent-config",
                "/console/agent-performance",
                "/console/portfolio",
                "/console/history",
            }:
                self.path = "/console/index.html"
                return super().do_GET()
            if route_path == "/api/config":
                return self._write_json(HTTPStatus.OK, service.load_config())
            if route_path == "/api/state":
                return self._write_json(HTTPStatus.OK, service.build_state())
            return super().do_GET()

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/api/config":
                content_length = int(self.headers.get("Content-Length", "0"))
                payload = {}
                if content_length > 0:
                    raw = self.rfile.read(content_length)
                    payload = json.loads(raw.decode("utf-8"))
                state = service.save_config(payload)
                return self._write_json(HTTPStatus.OK, {"status": "success", "state": state})
            if self.path != "/api/run":
                return self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            content_length = int(self.headers.get("Content-Length", "0"))
            payload = {}
            if content_length > 0:
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8"))
            try:
                state = service.start_simulation(payload)
            except RuntimeError as exc:
                return self._write_json(HTTPStatus.CONFLICT, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover - defensive API path
                return self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return self._write_json(HTTPStatus.ACCEPTED, state)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _write_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(body)

    return ControlConsoleHandler


def main() -> None:
    args = parse_args()
    config_path = (ROOT / args.config).resolve() if not pathlib.Path(args.config).is_absolute() else pathlib.Path(args.config)
    service = ConsoleService(ROOT, config_path)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    url = f"http://{args.host}:{args.port}/"
    print(f"Control console ready at {url}")
    print(f"Base config: {config_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Console stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
