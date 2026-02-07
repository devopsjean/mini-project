# Minimal webhook receiver image
# - Goal: prove Alertmanager delivery end-to-end without external SaaS (Slack/Email)
# - Keep it tiny and reproducible: single-file Python HTTP server + stdout logs

FROM python:3.11-slim

# Container working directory (simple, consistent paths for evidence/debugging)
WORKDIR /app

# Single-purpose server: receive POST from Alertmanager and print payload to stdout
COPY receiver.py /app/receiver.py

# Alertmanager webhook receiver port (must match alertmanager.yml receiver URL)
EXPOSE 9001

# Run the receiver in foreground so container logs become evidence artifactsg
CMD ["python", "/app/receiver.py"]