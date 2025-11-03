# Use the official Playwright Python image with browsers preinstalled
# Pick the tag that matches your Playwright version in requirements.txt
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

#--- Hardening / ergonomics ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Optional CSP relaxation and API key defaults (can be overridden at runtime)
ENV RELAXED_CSP=1 \
    API_KEY="secret123" \
    ADMIN_DEFAULT=1

# Workdir
WORKDIR /app

# Install Python deps first (better layer caching)
COPY requirements.txt .
# The base image already includes Playwright and browsers.
# We still install your app deps (Flask etc.)
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your app
COPY . .

# Expose Flask port
EXPOSE 5001

# Healthcheck with better error handling
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5001/api/health', timeout=5)" || exit 1

# Run with Flask's built-in server (perfect for development)
CMD ["python", "app.py"]