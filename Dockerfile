# Robuste Basis: Offizielles Playwright-Image (mehrarch, inkl. ARM64; bringt Systemdeps mit)
FROM mcr.microsoft.com/playwright/python:latest

WORKDIR /app

# 1) Code kopieren
COPY app /app

# 2) API-Dependencies + Playwright-Python installieren
#    (Playwright-Python ist meist schon dabei, wir installieren es aber explizit, um sicherzugehen.)
RUN pip install --no-cache-dir fastapi uvicorn[standard] playwright

# 3) Browser-Runtime (Chromium) sicherstellen
#    --with-deps: installiert systemweite Abhängigkeiten (im Base-Image meist bereits vorhanden)
RUN playwright install --with-deps chromium

# 4) Start der API
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]