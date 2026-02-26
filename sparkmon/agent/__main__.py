from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

from sparkmon.agent.sampler import Sampler


class Handler(BaseHTTPRequestHandler):
    # Set this before the server starts.
    sampler: Sampler

    def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/status"):
            self._send_json(200, self.sampler.snapshot())
            return
        if self.path == "/healthz":
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"error": "not found"})

    def log_message(self, format: str, *args) -> None:  # quiet
        return


def main() -> None:
    ap = argparse.ArgumentParser(prog="sparkmon-agent")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9000)
    args = ap.parse_args()

    sampler = Sampler()
    # IMPORTANT: BaseHTTPRequestHandler begins handling inside __init__.
    # So we must attach the sampler *before* instances are created.
    Handler.sampler = sampler

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    # block
    t.join()


if __name__ == "__main__":
    main()
