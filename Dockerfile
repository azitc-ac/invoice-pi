FROM mcr.microsoft.com/playwright/python:latest

WORKDIR /app
COPY app /app

RUN pip install --no-cache-dir fastapi uvicorn[standard]

CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
