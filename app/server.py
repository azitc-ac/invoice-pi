from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import List
from flows.freenet import run_freenet_download
from flows.netaachen import run_netaachen_download
import os
import subprocess
import time
import asyncio
import glob

app = FastAPI()

# ============================================================
# ADMIN UI
# ============================================================

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

@app.get("/admin", response_class=HTMLResponse)
def admin_ui():
    admin_path = os.path.join(STATIC_DIR, "admin.html")
    with open(admin_path, "r", encoding="utf-8") as f:
        return f.read()

# ============================================================
# API KEY MIDDLEWARE
# ============================================================

API_KEY = os.getenv("API_KEY", "")

def is_headless() -> bool:
    """Headless=False wenn Debug-Modus (VNC) aktiv, sonst aus .env"""
    if check_debug_mode():
        print("🖥️  Debug-Modus aktiv → headless=False")
        return False
    return os.getenv("HEADLESS", "true").lower() != "false"

@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    # Immer offen: Health-Check + Admin UI selbst (Login-Dialog ist in der Seite)
    # WebSocket Auth läuft über Query-Parameter
    if request.url.path in ("/health", "/admin", "/ws/logs"):
        return await call_next(request)

    # Kein API_KEY konfiguriert → durchlassen (Dev-Modus)
    if not API_KEY:
        return await call_next(request)

    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    return await call_next(request)


class DownloadRequest(BaseModel):
    site: str

# ============================================================
# DEBUG MODE - VNC Enable/Disable
# ============================================================

def get_supervisor_status(service_name):
    """Check if supervisor service is running"""
    try:
        result = subprocess.run(
            ["supervisorctl", "status", service_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        return "RUNNING" in result.stdout
    except Exception as e:
        print(f"Error checking {service_name} status: {e}")
        return False

def start_vnc_services():
    """Start all VNC-related services"""
    services = ["xvfb", "fluxbox", "x11vnc", "novnc"]
    results = {}
    
    for service in services:
        try:
            subprocess.run(
                ["supervisorctl", "start", service],
                capture_output=True,
                timeout=5
            )
            time.sleep(1)
            results[service] = get_supervisor_status(service)
        except Exception as e:
            results[service] = f"Error: {e}"
    
    return results

def stop_vnc_services():
    """Stop all VNC-related services"""
    services = ["novnc", "x11vnc", "fluxbox", "xvfb"]  # Stop in reverse order
    results = {}
    
    for service in services:
        try:
            subprocess.run(
                ["supervisorctl", "stop", service],
                capture_output=True,
                timeout=5
            )
            time.sleep(0.5)
            results[service] = not get_supervisor_status(service)
        except Exception as e:
            results[service] = f"Error: {e}"
    
    return results

def check_debug_mode():
    """Check if debug mode (VNC) is active"""
    return get_supervisor_status("novnc") and get_supervisor_status("xvfb")

def get_vnc_url(request: Request) -> str:
    """VNC URL dynamisch aus dem Request-Host bauen"""
    host = request.headers.get("host", "localhost").split(":")[0]
    return f"http://{host}:8081/vnc.html"

# ============================================================
# API ENDPOINTS - Download
# ============================================================

@app.post("/download")
def download(req: DownloadRequest):
    """Trigger Download, gibt Dateipfade zurück (lokale Speicherung)"""
    site = req.site.strip().lower()
    if site == "freenet":
        files = run_freenet_download(headless=is_headless())
        return {"status": "ok", "site": "freenet", "files": files}
    elif site == "netaachen":
        files = run_netaachen_download(headless=is_headless())
        return {"status": "ok", "site": "netaachen", "files": files}
    else:
        raise HTTPException(status_code=400, detail="Unsupported site")

@app.post("/download/file")
def download_file(req: DownloadRequest):
    """Trigger Download und liefere die PDF-Datei direkt zurück (für Power Automate)"""
    site = req.site.strip().lower()
    if site == "freenet":
        files: List[str] = run_freenet_download(headless=is_headless())
    elif site == "netaachen":
        files: List[str] = run_netaachen_download(headless=is_headless())
    else:
        raise HTTPException(status_code=400, detail="Unsupported site")
    
    if not files:
        raise HTTPException(status_code=500, detail="No file downloaded")
    
    path = files[0]
    if not os.path.isfile(path):
        raise HTTPException(status_code=500, detail=f"Downloaded file not found: {path}")
    
    filename = os.path.basename(path)
    
    if filename.lower().endswith(".pdf"):
        media_type = "application/pdf"
    elif filename.lower().endswith(".zip"):
        media_type = "application/zip"
    else:
        media_type = "application/octet-stream"
    
    return FileResponse(
        path=path,
        media_type=media_type,
        filename=filename,  # originaler Dateiname bleibt erhalten
    )
# ============================================================
# API ENDPOINTS - Session Init (manueller Login)
# ============================================================

def _open_browser_for_login(site: str):
    """
    Öffnet Browser mit vorausgefüllten Credentials.
    User muss nur noch auf Anmelden klicken.
    Browser bleibt 5 Minuten offen → Session wird in pwdata gespeichert.
    """
    from playwright.sync_api import sync_playwright

    configs = {
        "freenet": {
            "url": "https://www.freenet-mobilfunk.de/onlineservice/meine-rechnungen",
            "userdata": os.getenv("PW_USERDATA_FREENET", "/pwdata/freenet"),
            "username": os.getenv("FREENET_USERNAME", ""),
            "password": os.getenv("FREENET_PASSWORD", ""),
            "fill_username": "input#username",
            "fill_password": "input#password",
        },
        "netaachen": {
            "url": "https://sso.netcologne.de/cas/login?service=https://meinekundenwelt.netcologne.de/&mandant=na",
            "userdata": os.getenv("PW_USERDATA_NETAACHEN", "/pwdata/netaachen"),
            "username": os.getenv("NETAACHEN_USERNAME", ""),
            "password": os.getenv("NETAACHEN_PASSWORD", ""),
            "fill_username": "input#username",
            "fill_password": "input#password",
        },
    }

    cfg = configs[site]

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=cfg["userdata"],
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-setuid-sandbox"],
        )
        page = context.new_page()
        print(f"📖 Öffne Login-Seite für {site}: {cfg['url']}")
        page.goto(cfg["url"], wait_until="domcontentloaded")
        time.sleep(2)

        # Credentials vorausfüllen
        try:
            page.fill(cfg["fill_username"], cfg["username"])
            page.fill(cfg["fill_password"], cfg["password"])
            print(f"✅ Credentials vorausgefüllt für {site} — warte auf manuellen Login...")
        except Exception as e:
            print(f"⚠️  Konnte Credentials nicht einfüllen: {e}")

        # 5 Minuten offen lassen für manuellen Login + Navigation
        time.sleep(300)
        print(f"⏰ Timeout erreicht, Browser wird geschlossen. Session gespeichert in {cfg['userdata']}")
        context.close()


@app.post("/session/init")
def session_init(req: DownloadRequest, request: Request):
    """
    Öffnet Browser im GUI-Modus mit vorausgefüllten Credentials.
    User klickt manuell auf Anmelden → Session wird gespeichert.
    Voraussetzung: Debug-Modus muss aktiv sein (POST /debug/enable).
    """
    import threading

    if not check_debug_mode():
        raise HTTPException(
            status_code=400,
            detail="Debug-Modus nicht aktiv. Erst POST /debug/enable aufrufen."
        )

    site = req.site.strip().lower()
    if site not in ("freenet", "netaachen"):
        raise HTTPException(status_code=400, detail="Unsupported site")

    thread = threading.Thread(target=_open_browser_for_login, args=(site,), daemon=True)
    thread.start()

    return {
        "status": "ok",
        "site": site,
        "message": "Browser geöffnet, Credentials vorausgefüllt. Bitte manuell auf Anmelden klicken.",
        "vnc_url": get_vnc_url(request),
        "timeout_minutes": 5,
    }


# ============================================================
# API ENDPOINTS - Health & Debug
# ============================================================

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/debug/status")
def debug_status(request: Request):
    """Check debug mode status"""
    is_enabled = check_debug_mode()
    
    return {
        "debug_enabled": is_enabled,
        "vnc_url": get_vnc_url(request) if is_enabled else None,
        "services": {
            "xvfb": get_supervisor_status("xvfb"),
            "fluxbox": get_supervisor_status("fluxbox"),
            "x11vnc": get_supervisor_status("x11vnc"),
            "novnc": get_supervisor_status("novnc"),
            "fastapi": get_supervisor_status("fastapi"),
        }
    }

@app.post("/debug/enable")
def debug_enable(request: Request):
    """Enable debug mode (start VNC services)"""
    
    if check_debug_mode():
        return {
            "status": "already_enabled",
            "message": "Debug mode is already active",
            "vnc_url": get_vnc_url(request)
        }
    
    print("🚀 Starting VNC services...")
    results = start_vnc_services()
    
    time.sleep(3)
    
    is_enabled = check_debug_mode()
    
    return {
        "status": "enabled" if is_enabled else "partial",
        "message": "Debug mode activated - VNC services started",
        "vnc_url": get_vnc_url(request) if is_enabled else None,
        "services": results
    }

@app.post("/debug/disable")
def debug_disable():
    """Disable debug mode (stop VNC services)"""
    
    if not check_debug_mode():
        return {
            "status": "already_disabled",
            "message": "Debug mode is already inactive"
        }
    
    print("🛑 Stopping VNC services...")
    results = stop_vnc_services()
    
    time.sleep(1)
    
    is_disabled = not check_debug_mode()
    
    return {
        "status": "disabled" if is_disabled else "partial",
        "message": "Debug mode deactivated - VNC services stopped",
        "services": results
    }

# ============================================================
# WEBSOCKET - Live Log Stream
# ============================================================

def find_log_file() -> str | None:
    """Findet die aktuelle fastapi-stdout Logdatei"""
    matches = glob.glob("/var/log/supervisor/fastapi-stdout---supervisor-*.log")
    return matches[0] if matches else None

@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket, api_key: str = ""):
    # Auth prüfen (WebSocket kann keine HTTP-Header senden, daher Query-Parameter)
    if API_KEY and api_key != API_KEY:
        await websocket.close(code=1008)  # Policy violation
        return

    await websocket.accept()
    log_path = find_log_file()

    if not log_path:
        await websocket.send_text("⚠️  Log-Datei nicht gefunden")
        await websocket.close()
        return

    try:
        # Sende letzte 50 Zeilen als History
        proc = await asyncio.create_subprocess_exec(
            "tail", "-n", "50", log_path,
            stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        for line in stdout.decode(errors="replace").splitlines():
            await websocket.send_text(line)

        # Dann live tail -f
        proc = await asyncio.create_subprocess_exec(
            "tail", "-f", "-n", "0", log_path,
            stdout=asyncio.subprocess.PIPE
        )

        while True:
            line = await proc.stdout.readline()
            if not line:
                await asyncio.sleep(0.1)
                continue
            await websocket.send_text(line.decode(errors="replace").rstrip())

    except WebSocketDisconnect:
        proc.terminate()
    except Exception as e:
        await websocket.send_text(f"❌ Log-Stream-Fehler: {e}")
        await websocket.close()
