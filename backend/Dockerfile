# Dockerfile
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Make Playwright use local project folder (kept in layer cache)
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    # Make Chromium launch faster
    PWEXTRA_LAUNCH_ARGS="--no-sandbox --disable-dev-shm-usage --disable-gpu --disable-extensions" \
    # Force headless unless overridden
    HEADFUL=0

# System deps for Chromium & fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    libasound2 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdbus-1-3 \
    libdrm2 libgtk-3-0 libnspr4 libnss3 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libpangocairo-1.0-0 \
    libxkbcommon0 libwayland-client0 ca-certificates fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright + Chromium into image
RUN python -m playwright install chromium --with-deps

COPY . /app

# Run as non-root
RUN useradd -m appuser
USER appuser

EXPOSE 5001

# Gunicorn: 2 workers, threads 4 (IO-bound), reasonable timeouts
CMD ["bash", "-lc", "gunicorn -w 2 -k gthread --threads 4 --timeout 30 --keep-alive 5 --bind 0.0.0.0:5001 app:app"]
