FROM mcr.microsoft.com/playwright/python:latest

ENV DEBIAN_FRONTEND noninteractive
ENV DISPLAY :0
ENV RES 1280x900x24

# Install VNC + GUI components (OHNE websockify!)
RUN apt-get update && apt-get -y install \
    xvfb x11vnc \
    supervisor fluxbox \
    net-tools wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Download noVNC lokal (wie das alte solarkennedy Setup!)
RUN mkdir -p /root && \
    cd /root && \
    wget -q https://github.com/novnc/noVNC/archive/refs/tags/v1.3.0.tar.gz && \
    tar -xzf v1.3.0.tar.gz && \
    mv noVNC-1.3.0 novnc && \
    rm v1.3.0.tar.gz && \
    chmod +x /root/novnc/utils/novnc_proxy

WORKDIR /app

# Copy code
COPY app /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn[standard] playwright

# Ensure Chromium is installed with dependencies (Playwright's version, nicht System-Paket!)
RUN playwright install --with-deps chromium

# Create directories
RUN mkdir -p /pwdata /downloads /root/images

# Create supervisor config
RUN mkdir -p /etc/supervisor/conf.d && \
    echo '[supervisord]' > /etc/supervisor/conf.d/supervisord.conf && \
    echo 'nodaemon=true' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'user=root' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo '' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo '[program:xvfb]' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'command=/usr/bin/Xvfb :0 -screen 0 1280x900x24' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'autostart=true' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'autorestart=true' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'startsecs=0' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'priority=1' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo '' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo '[program:fluxbox]' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'command=/usr/bin/fluxbox' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'autostart=true' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'autorestart=true' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'environment=DISPLAY=:0' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'priority=2' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo '' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo '[program:x11vnc]' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'command=/usr/bin/x11vnc -display :0 -forever -nopw' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'autostart=true' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'autorestart=true' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'environment=DISPLAY=:0' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'priority=3' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo '' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo '[program:novnc]' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'command=python3 /root/novnc/utils/novnc_proxy --vnc localhost:5900 --listen 8080' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'autostart=true' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'autorestart=true' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'priority=4' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo '' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo '[program:fastapi]' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'command=python -m uvicorn server:app --host 0.0.0.0 --port 8000' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'directory=/app' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'autostart=true' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'autorestart=true' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'environment=DISPLAY=:0' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'priority=5' >> /etc/supervisor/conf.d/supervisord.conf

EXPOSE 8080 8000 5900

CMD ["/usr/bin/supervisord"]
