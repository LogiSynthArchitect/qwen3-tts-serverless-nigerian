#!/usr/bin/env python3
"""Standalone diagnostic HTTP server for Vast.ai instances.

Serves the onstart + app log and process list on :8001 so we can diagnose
the instance over HTTP without SSH (Vast's SSH proxy is unreliable here).

Run in the BACKGROUND by vast_start.sh; it stays up regardless of whether the
main serve.py is running, so /log is always reachable.
"""
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG_PATH = "/workspace/onstart.log"


def _read_log(tail=8000):
    try:
        with open(LOG_PATH) as f:
            return f.read()[-tail:]
    except Exception as e:
        return f"(no log file: {e})"


def _ps():
    try:
        return subprocess.run(["ps", "-eo", "pid,etimes,cmd"],
                              capture_output=True, text=True, timeout=5).stdout
    except Exception as e:
        return str(e)


class H(BaseHTTPRequestHandler):
    def _send(self, obj):
        body = __import__("json").dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/log":
            self._send({"log": _read_log()})
        elif self.path == "/ps":
            self._send({"ps": _ps()})
        elif self.path == "/health":
            self._send({"status": "diag-ok"})
        else:
            self._send({"error": "unknown path", "paths": ["/log", "/ps", "/health"]})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("diag server on :8001", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8001), H).serve_forever()
