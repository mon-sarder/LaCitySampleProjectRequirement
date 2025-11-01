# Uses Ubuntu Jammy + Playwright browsers preinstalled (arm64-compatible)
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

# If requirements.txt includes "playwright==1.48.0" it's fine; the image already matches.
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

ENV FLASK_APP=app.py \
    PYTHONUNBUFFERED=1 \
    RELAXED_CSP=1

EXPOSE 5001

# Production server
RUN pip install --no-cache-dir gunicorn
CMD ["gunicorn", "-w", "2", "-k", "gthread", "-b", "0.0.0.0:5001", "app:app"]
