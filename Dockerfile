FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy
ENV DEBIAN_FRONTEND noninteractive
ENV DISPLAY :0
ENV RES 1280x900x24
# Install VNC + GUI components
RUN apt-get update && apt-get -y install \
    xvfb x11vnc \
    supervisor fluxbox \
    net-tools wget && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
# Install websockify separately (critical for noVNC on ARM64 - separate apt-get update required)
RUN apt-get update && apt-get install -y websockify && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
# Install firefox-esr + xdotool + xclip for real browser login
RUN apt-get update && apt-get install -y \
    firefox-esr \
    xdotool \
    xclip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
# Download noVNC
RUN mkdir -p /root && \
    cd /root && \
    wget -q https://github.com/novnc/noVNC/archive/refs/tags/v1.3.0.tar.gz && \
    tar -xzf v1.3.0.tar.gz && \
    mv noVNC-1.3.0 novnc && \
    rm v1.3.0.tar.gz
# Create launch.sh script
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
WORKDIR /app
# Copy code
COPY app /app
# Copy supervisor config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn[standard] playwright python-multipart
# Ensure Chromium is installed
RUN playwright install --with-deps chromium
# Create directories
RUN mkdir -p /pwdata /downloads /root/images
EXPOSE 8080 8000 5900
CMD ["/usr/bin/supervisord"]
