FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libasound2 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libdbus-1-3 \
    libgtk-3-0 libnss3 libx11-xcb1 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libxkbcommon0 libxshmfence1 libxext6 libxrender1 \
    ca-certificates wget fonts-liberation libgbm1 xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

RUN python -m playwright install --with-deps

COPY . /app/

ENV FLASK_APP=app.py \
    PYTHONUNBUFFERED=1 \
    RELAXED_CSP=1

EXPOSE 5001

RUN pip install --no-cache-dir gunicorn
CMD ["gunicorn", "-w", "2", "-k", "gthread", "-b", "0.0.0.0:5001", "app:app"]
