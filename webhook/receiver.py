from http.server import BaseHTTPRequestHandler, HTTPServer

# Minimal Alertmanager webhook receiver
# - Purpose: validate alert delivery end-to-end (Prometheus -> Alertmanager -> Webhook)
# - Design choice: use Python stdlib to avoid extra dependencies (reproducibility-first)
# - Evidence: print request path/headers/body to stdout so docker logs can be used as proof

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Alertmanager sends JSON payload via POST.
        # content-length may be missing/0, so default to 0 to avoid crashes.
        length = int(self.headers.get('content-length', 0))

        # Read raw request body and decode safely:
        # - errors='replace' prevents crash on unexpected bytes
        body = self.rfile.read(length).decode('utf-8', errors='replace')

        # Evidence output (used for screenshots/log capture in the report)
        print("=== Alertmanager Webhook Received ===")
        print(f"Path: {self.path}")
        print("Headers:", dict(self.headers))
        print("Body:", body)

        # Always return 200 so Alertmanager treats delivery as successful.
        # (Non-2xx would trigger retries and may confuse demo evidence.)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

# Bind to all interfaces for container networking.
# Port 9001 must match alertmanager.yml receiver URL (http://webhook:9001/)
HTTPServer(("0.0.0.0", 9001), Handler).serve_forever()
