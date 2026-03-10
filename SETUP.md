# Invoice-Pi Setup & Architecture

## Quick Start
```bash
docker compose up --build
POST http://localhost:8000/download?site=freenet
```

## Key Files
- `app/server.py` - FastAPI with debug mode toggle
- `app/flows/freenet.py` - Freenet downloader
- `app/flows/freenet-login-helper.py` - Session manager
- `app/flows/netaachen.py` - NetAachen downloader
- `app/flows/netaachen-login-helper.py` - Session manager

## Debug Mode
```bash
POST /debug/enable   # Start VNC (http://localhost:8081/vnc.html)
POST /debug/disable  # Stop VNC
GET /debug/status    # Check status
```

## Critical Discovery
- Use `/root/novnc/utils/launch.sh` NOT `apt-get websockify`
- Install websockify as root in Dockerfile
- Playwright Official Image (mcr.microsoft.com/playwright/python)