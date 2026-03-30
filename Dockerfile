FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy
ENV DEBIAN_FRONTEND noninteractive
ENV DISPLAY :0
ENV RES 1280x900x24

# Install VNC + GUI + OCR components
RUN apt-get update && apt-get -y install \
    xvfb x11vnc \
    supervisor fluxbox \
    net-tools wget \
    tesseract-ocr tesseract-ocr-deu \
    poppler-utils && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install websockify separately (critical for noVNC on ARM64)
RUN apt-get update && apt-get install -y websockify && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install xdotool + xclip
RUN apt-get update && apt-get install -y xdotool xclip wget ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Firefox from Mozilla APT repo (official ARM64 support)
RUN mkdir -p /etc/apt/keyrings && \
    wget -q https://packages.mozilla.org/apt/repo-signing-key.gpg -O /etc/apt/keyrings/packages.mozilla.org.asc && \
    echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" > /etc/apt/sources.list.d/mozilla.list && \
    printf 'Package: *\nPin: origin packages.mozilla.org\nPin-Priority: 1000\n' > /etc/apt/preferences.d/mozilla && \
    apt-get update && apt-get install -y --allow-downgrades firefox && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install geckodriver (automatische Architektur-Erkennung: ARM64 + x86_64)
RUN ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "arm64" ]; then \
        GD_FILE="geckodriver-v0.35.0-linux-aarch64.tar.gz"; \
    else \
        GD_FILE="geckodriver-v0.35.0-linux64.tar.gz"; \
    fi && \
    wget -q "https://github.com/mozilla/geckodriver/releases/download/v0.35.0/${GD_FILE}" -O /tmp/gd.tar.gz && \
    tar -xz -C /usr/local/bin -f /tmp/gd.tar.gz && \
    rm /tmp/gd.tar.gz && \
    geckodriver --version

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

# Install Python dependencies
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn[standard] \
    playwright \
    python-multipart \
    pdfplumber \
    pytesseract \
    pdf2image

# Ensure Chromium is installed
RUN playwright install --with-deps chromium

# Create directories
RUN mkdir -p /pwdata /downloads /uploads /root/images

EXPOSE 8080 8000 5900
CMD ["/usr/bin/supervisord"]
