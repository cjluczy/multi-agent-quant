#!/usr/bin/env python
"""Serve runtime artifacts for quick local review."""
from __future__ import annotations

import argparse
import http.server
import os
import pathlib
import socketserver
import webbrowser


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the local runtime dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the browser automatically",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = pathlib.Path(__file__).resolve().parents[1]
    runtime_dir = root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(root)

    handler = http.server.SimpleHTTPRequestHandler
    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    with ReusableTCPServer((args.host, args.port), handler) as server:
        url = f"http://{args.host}:{args.port}/runtime/dashboard.html"
        print(f"Serving {root}")
        print(f"Open {url}")
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Server stopped")


if __name__ == "__main__":
    main()
