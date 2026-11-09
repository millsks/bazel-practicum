"""Serve the curriculum website locally."""

import functools
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_CONTENT_TYPES = {**SimpleHTTPRequestHandler.extensions_map, ".mjs": "text/javascript", ".wasm": "application/wasm"}


class _Handler(SimpleHTTPRequestHandler):
    extensions_map = _CONTENT_TYPES

    def log_message(self, format: str, *args: object) -> None:
        """Silence per-request access logging."""


def make_server(site_root: Path, host: str, port: int) -> ThreadingHTTPServer:
    """Create an HTTP server that serves ``site_root``.

    Args:
        site_root: Directory to serve.
        host: Interface to bind.
        port: Port to bind; 0 picks a free port.

    Returns:
        A server that has not started serving yet.
    """
    handler = functools.partial(_Handler, directory=str(site_root))
    return ThreadingHTTPServer((host, port), handler)


def serve(site_root: Path, host: str = "127.0.0.1", port: int = 8000, *, open_browser: bool = True) -> None:
    """Serve the site until interrupted.

    Args:
        site_root: Directory to serve.
        host: Interface to bind.
        port: Port to bind.
        open_browser: Open the home page in the default browser.
    """
    with make_server(site_root, host, port) as server:
        bound_port = server.server_address[1]
        if open_browser:
            webbrowser.open(f"http://{host}:{bound_port}/")
        server.serve_forever()
