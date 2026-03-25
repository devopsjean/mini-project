# Base image selection
# - python:3.11-slim
#   * Uses a slim Debian-based image to reduce image size
#   * Faster build and pull times for local experiments and demos
# - Debian-slim is chosen over Alpine:
#   * Avoids potential issues with musl vs glibc for Python dependencies
#   * More predictable behavior for common Python tooling (uvicorn, prometheus client)
FROM python:3.11-slim

# Disable .pyc file generation
# - Containers are treated as immutable artifacts
# - Prevents unnecessary filesystem writes and keeps the image clean
ENV PYTHONDONTWRITEBYTECODE=1

# Disable stdout/stderr buffering
# - Ensures logs are immediately visible via `docker logs`
# - Important for incident investigation and real-time debugging
ENV PYTHONUNBUFFERED=1

# Set application working directory
# - Keeps path conventions consistent across Dockerfile, docker-compose, and README
WORKDIR /app

# (Optional) System dependencies
# - Not required for this project at the moment
# - Left here intentionally as an extension point if native dependencies are needed later
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     && rm -rf /var/lib/apt/lists/*

# Copy dependency definitions first
# - Enables Docker layer caching
# - Dependency installation is skipped if requirements.txt has not changed
COPY requirements.txt .

# Install Python dependencies
# - --no-cache-dir reduces final image size
# - Versions are pinned in requirements.txt to ensure reproducibility
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
# - FastAPI application exposing:
#   /health   : normal response
#   /metrics  : Prometheus metrics
#   /slow     : intentional latency injection
#   /error    : intentional 5xx error injection
COPY . .

# Document the application port
# - Informational only (actual port binding is handled by docker-compose)
# - Keeps port usage explicit and consistent across the stack
EXPOSE 8080

# Application startup command
# - Run FastAPI using uvicorn
# - --host 0.0.0.0 allows access from other containers
# - --port 8080 matches docker-compose and Prometheus scrape configuration
# - Auto-reload is intentionally disabled for predictable runtime behavior
# - Access log is disabled because the app emits structured JSON request logs itself
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
