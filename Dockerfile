FROM mcr.microsoft.com/playwright/python:latest

ENV DEBIAN_FRONTEND noninteractive
ENV DISPLAY :0
ENV RES 1280x900x24

# Install VNC + GUI components (AS ROOT!)
RUN apt-get update && apt-get -y install \
    xvfb x11vnc \
    supervisor fluxbox \
    net-tools wget && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install websockify separately AS ROOT (critical for noVNC)
RUN apt-get update && apt-get install -y websockify && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Download noVNC lokal (wie das alte solarkennedy Setup!)
RUN mkdir -p /root && \
    cd /root && \
    wget -q https://github.com/novnc/noVNC/archive/refs/tags/v1.3.0.tar.gz && \
    tar -xzf v1.3.0.tar.gz && \
    mv noVNC-1.3.0 novnc && \
    rm v1.3.0.tar.gz

# Erstelle launch.sh Script (wie das alte solarkennedy Setup)
RUN echo '#!/bin/bash' > /root/novnc/utils/launch.sh && \
    echo 'PORT="6080"' >> /root/novnc/utils/launch.sh && \
    echo 'VNC_DEST="localhost:5900"' >> /root/novnc/utils/launch.sh && \
    echo 'WEB=""' >> /root/novnc/utils/launch.sh && \
    echo 'while [ "$*" ]; do' >> /root/novnc/utils/launch.sh && \
    echo '    param=$1; shift; OPTARG=$1' >> /root/novnc/utils/launch.sh && \
    echo '    case $param in' >> /root/novnc/utils/launch.sh && \
    echo '    --listen)  PORT="${OPTARG}"; shift            ;;' >> /root/novnc/utils/launch.sh && \
    echo '    --vnc)     VNC_DEST="${OPTARG}"; shift        ;;' >> /root/novnc/utils/launch.sh && \
    echo '    --web)     WEB="${OPTARG}"; shift            ;;' >> /root/novnc/utils/launch.sh && \
    echo '    *) shift                                      ;;' >> /root/novnc/utils/launch.sh && \
    echo '    esac' >> /root/novnc/utils/launch.sh && \
    echo 'done' >> /root/novnc/utils/launch.sh && \
    echo 'if [ -z "${WEB}" ]; then' >> /root/novnc/utils/launch.sh && \
    echo '    WEB="/root/novnc"' >> /root/novnc/utils/launch.sh && \
    echo 'fi' >> /root/novnc/utils/launch.sh && \
    echo 'echo "Starting WebSockets proxy on port ${PORT}"' >> /root/novnc/utils/launch.sh && \
    echo 'exec /usr/bin/websockify --web ${WEB} ${PORT} ${VNC_DEST}' >> /root/novnc/utils/launch.sh && \
    chmod +x /root/novnc/utils/launch.sh

# Copy Python scripts for invoice downloading

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
    echo 'command=bash /root/novnc/utils/launch.sh --vnc localhost:5900 --listen 8080' >> /etc/supervisor/conf.d/supervisord.conf && \
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
