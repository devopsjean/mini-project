from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import sys
from datetime import datetime, timezone

# Minimal Alertmanager webhook receiver
# - Purpose: validate alert delivery end-to-end (Prometheus -> Alertmanager -> Webhook)
# - Design choice: use Python stdlib to avoid extra dependencies (reproducibility-first)
# - Evidence: emit one JSON log line per event so Loki can parse/query it easily


def _build_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


webhook_logger = _build_logger("mini_project.webhook")


def log_event(level: str, event: str, **fields) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "service": "webhook",
        "event": event,
    }
    payload.update(fields)
    webhook_logger.info(json.dumps(payload, sort_keys=True))

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress BaseHTTPRequestHandler plain-text access logs.
        return

    def do_POST(self):
        # Alertmanager sends JSON payload via POST.
        # content-length may be missing/0, so default to 0 to avoid crashes.
        length = int(self.headers.get("content-length", 0))

        # Read raw request body and decode safely:
        # - errors='replace' prevents crash on unexpected bytes
        body = self.rfile.read(length).decode("utf-8", errors="replace")

        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            log_event(
                "warning",
                "alertmanager_webhook_invalid_json",
                method="POST",
                path=self.path,
                content_length=length,
                raw_body=body,
            )
            payload = {}

        alerts = payload.get("alerts", [])
        alert_names = sorted(
            {
                alert.get("labels", {}).get("alertname", "unknown")
                for alert in alerts
            }
        )
        alert_statuses = sorted({alert.get("status", "unknown") for alert in alerts})

        log_event(
            "info",
            "alertmanager_webhook_received",
            method="POST",
            path=self.path,
            content_length=length,
            receiver=payload.get("receiver"),
            webhook_status=payload.get("status"),
            group_key=payload.get("groupKey"),
            alert_count=len(alerts),
            alert_names=alert_names,
            alert_statuses=alert_statuses,
            common_labels=payload.get("commonLabels", {}),
        )

        # Always return 200 so Alertmanager treats delivery as successful.
        # (Non-2xx would trigger retries and may confuse demo evidence.)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

# Bind to all interfaces for container networking.
# Port 9001 must match alertmanager.yml receiver URL (http://webhook:9001/)
log_event("info", "webhook_server_started", port=9001)
HTTPServer(("0.0.0.0", 9001), Handler).serve_forever()
