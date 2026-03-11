from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import List, Optional
from flows.freenet import run_freenet_download
from flows.netaachen import run_netaachen_download
from flows.lexware import run_lexware_upload
import os
import subprocess
import time
import asyncio
import glob
import shutil
import tempfile

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
    if request.url.path in ("/health", "/admin", "/ws/logs"):
        return await call_next(request)

    if not API_KEY:
        return await call_next(request)

    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    return await call_next(request)


class DownloadRequest(BaseModel):
    site: str
    month_offset: int = 0


# ============================================================
# API ENDPOINT - Cleanup Locks
# ============================================================

PW_USERDIRS = {
    "freenet": os.getenv("PW_USERDATA_FREENET", "/pwdata/freenet"),
    "netaachen": os.getenv("PW_USERDATA_NETAACHEN", "/pwdata/netaachen"),
    "lexware": os.getenv("PW_USERDATA_LEXWARE", "/pwdata/lexware"),
}
LOCK_FILES = ["SingletonLock", "SingletonCookie", "SingletonSocket"]

@app.post("/cleanup/locks")
def cleanup_locks():
    """Entfernt stale Chromium Lock-Dateien und killt verwaiste Prozesse"""
    removed = []
    for site, userdir in PW_USERDIRS.items():
        for lf in LOCK_FILES:
            path = os.path.join(userdir, lf)
            if os.path.exists(path):
                os.remove(path)
                removed.append(path)
                print(f"🧹 Lock entfernt: {path}")

    try:
        subprocess.run(["pkill", "-f", "chromium"], capture_output=True)
        print("🧹 Chromium-Prozesse beendet")
    except Exception:
        pass

    msg = f"{len(removed)} Lock(s) entfernt" if removed else "Keine Locks gefunden"
    return {"status": "ok", "message": msg, "removed": removed}


# ============================================================
# DEBUG MODE - VNC Enable/Disable
# ============================================================

def get_supervisor_status(service_name):
    try:
        result = subprocess.run(
            ["supervisorctl", "status", service_name],
            capture_output=True, text=True, timeout=5
        )
        return "RUNNING" in result.stdout
    except Exception as e:
        print(f"Error checking {service_name} status: {e}")
        return False

def start_vnc_services():
    services = ["xvfb", "fluxbox", "x11vnc", "novnc"]
    results = {}
    for service in services:
        try:
            subprocess.run(["supervisorctl", "start", service], capture_output=True, timeout=5)
            time.sleep(1)
            results[service] = get_supervisor_status(service)
        except Exception as e:
            results[service] = f"Error: {e}"
    return results

def stop_vnc_services():
    services = ["novnc", "x11vnc", "fluxbox", "xvfb"]
    results = {}
    for service in services:
        try:
            subprocess.run(["supervisorctl", "stop", service], capture_output=True, timeout=5)
            time.sleep(0.5)
            results[service] = not get_supervisor_status(service)
        except Exception as e:
            results[service] = f"Error: {e}"
    return results

def check_debug_mode():
    return get_supervisor_status("novnc") and get_supervisor_status("xvfb")

def get_vnc_url(request: Request) -> str:
    host = request.headers.get("host", "localhost").split(":")[0]
    return f"http://{host}:8081/vnc.html"


# ============================================================
# API ENDPOINTS - Download
# ============================================================

@app.post("/download")
def download(req: DownloadRequest):
    site = req.site.strip().lower()
    if site == "freenet":
        files = run_freenet_download(headless=is_headless(), month_offset=req.month_offset)
        return {"status": "ok", "site": "freenet", "files": files}
    elif site == "netaachen":
        files = run_netaachen_download(headless=is_headless(), month_offset=req.month_offset)
        return {"status": "ok", "site": "netaachen", "files": files}
    else:
        raise HTTPException(status_code=400, detail="Unsupported site")

@app.post("/download/file")
def download_file(req: DownloadRequest):
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

    return FileResponse(path=path, media_type=media_type, filename=filename)


# ============================================================
# API ENDPOINTS - Upload (Lexware)
# ============================================================

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/upload/lexware")
async def upload_lexware(file: UploadFile = File(...)):
    """
    Nimmt eine hochgeladene PDF-Datei entgegen und lädt sie via Playwright zu Lexware hoch.
    Erwartet multipart/form-data mit field 'file'.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Kein Dateiname")

    # Datei temporär speichern
    safe_name = os.path.basename(file.filename)
    tmp_path = os.path.join(UPLOAD_DIR, safe_name)

    try:
        with open(tmp_path, "wb") as f:
            content = await file.read()
            f.write(content)
        print(f"📥 Datei empfangen: {tmp_path} ({len(content)} bytes)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Speichern: {e}")

    try:
        result = run_lexware_upload(file_path=tmp_path, headless=is_headless())
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload fehlgeschlagen: {e}")


@app.post("/upload/lexware/path")
def upload_lexware_by_path(req: dict):
    """
    Alternativer Endpoint: Lädt eine bereits lokal gespeicherte Datei zu Lexware hoch.
    Body: { "file_path": "/downloads/Rechnung_Freenet_2026-02.pdf" }
    """
    file_path = req.get("file_path", "").strip()
    if not file_path:
        raise HTTPException(status_code=400, detail="file_path fehlt")
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail=f"Datei nicht gefunden: {file_path}")

    try:
        result = run_lexware_upload(file_path=file_path, headless=is_headless())
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload fehlgeschlagen: {e}")


@app.get("/uploads/list")
def list_uploads():
    """Listet alle Dateien im Upload-Verzeichnis auf"""
    try:
        files = []
        for f in sorted(os.listdir(UPLOAD_DIR)):
            full = os.path.join(UPLOAD_DIR, f)
            if os.path.isfile(full):
                files.append({
                    "name": f,
                    "path": full,
                    "size": os.path.getsize(full),
                })
        return {"status": "ok", "files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/downloads/list")
def list_downloads():
    """Listet alle Dateien im Download-Verzeichnis auf"""
    download_dir = os.getenv("DOWNLOAD_DIR", "/downloads")
    try:
        files = []
        for f in sorted(os.listdir(download_dir)):
            full = os.path.join(download_dir, f)
            if os.path.isfile(full) and f.endswith(".pdf"):
                files.append({
                    "name": f,
                    "path": full,
                    "size": os.path.getsize(full),
                })
        return {"status": "ok", "files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# API ENDPOINTS - Session Init (manueller Login)
# ============================================================

ANTI_DETECTION_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Plugin' },
            { name: 'Chrome PDF Viewer' },
            { name: 'Native Client' }
        ],
    });
    Object.defineProperty(navigator, 'languages', {
        get: () => ['de-DE', 'de', 'en-US', 'en'],
    });
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (p) => (
        p.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(p)
    );
"""

def _open_browser_for_login(site: str):
    from playwright.sync_api import sync_playwright

    configs = {
        "freenet": {
            "url": "https://www.freenet-mobilfunk.de/onlineservice/meine-rechnungen",
            "userdata": os.getenv("PW_USERDATA_FREENET", "/pwdata/freenet"),
            "username": os.getenv("FREENET_USERNAME", ""),
            "password": os.getenv("FREENET_PASSWORD", ""),
            "fill_username": "input#username",
            "fill_password": "input#password",
            "anti_detection": False,
        },
        "netaachen": {
            "url": "https://sso.netcologne.de/cas/login?service=https://meinekundenwelt.netcologne.de/&mandant=na",
            "userdata": os.getenv("PW_USERDATA_NETAACHEN", "/pwdata/netaachen"),
            "username": os.getenv("NETAACHEN_USERNAME", ""),
            "password": os.getenv("NETAACHEN_PASSWORD", ""),
            "fill_username": "input#username",
            "fill_password": "input#password",
            "anti_detection": False,
        },
        "lexware": {
            "url": "https://lexware.de",
            "userdata": os.getenv("PW_USERDATA_LEXWARE", "/pwdata/lexware"),
            "username": os.getenv("LEXWARE_USERNAME", ""),
            "password": os.getenv("LEXWARE_PASSWORD", ""),
            "fill_username": "input[type='email']",
            "fill_password": "input[type='password']",
            "anti_detection": True,  # Lexware erkennt Bots — Anti-Detection aktiv
        },
    }

    cfg = configs[site]

    with sync_playwright() as p:
        launch_args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
        ]
        if cfg["anti_detection"]:
            launch_args += [
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--start-maximized",
            ]

        context_kwargs = dict(
            user_data_dir=cfg["userdata"],
            headless=False,
            args=launch_args,
        )
        if cfg["anti_detection"]:
            context_kwargs["user_agent"] = (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
            context_kwargs["viewport"]    = {"width": 1280, "height": 900}
            context_kwargs["locale"]      = "de-DE"
            context_kwargs["timezone_id"] = "Europe/Berlin"

        context = p.chromium.launch_persistent_context(**context_kwargs)

        if cfg["anti_detection"]:
            context.add_init_script(ANTI_DETECTION_SCRIPT)

        page = context.new_page()
        print(f"📖 Öffne Login-Seite für {site}: {cfg['url']}")
        page.goto(cfg["url"], wait_until="domcontentloaded")
        time.sleep(2)

        if not cfg["anti_detection"]:
            # Freenet / NetAachen: automatisch vorausfüllen
            try:
                if cfg["username"]:
                    page.fill(cfg["fill_username"], cfg["username"])
                if cfg["password"]:
                    page.fill(cfg["fill_password"], cfg["password"])
                print(f"✅ Credentials vorausgefüllt für {site} — warte auf manuellen Login...")
            except Exception as e:
                print(f"⚠️  Konnte Credentials nicht einfüllen: {e}")
        else:
            # Lexware: Browser komplett leer öffnen — kein automatisches Ausfüllen.
            # Lexware erkennt synthetische Events und blockiert den Login-Button.
            u = cfg["username"] or "(nicht in .env — LEXWARE_USERNAME)"
            pw_hint = cfg["password"][:2] + "***" if cfg["password"] else "(nicht in .env — LEXWARE_PASSWORD)"
            print(f"")
            print(f"🔐 Bitte manuell im Browser eingeben:")
            print(f"   👤 {u}")
            print(f"   🔑 {pw_hint}")
            print(f"")
            print(f"👉 Daten eingeben → Anmelden klicken → warten bis eingeloggt.")
            print(f"   Browser schließt automatisch nach 5 Minuten.")

        time.sleep(300)
        print(f"⏰ Timeout erreicht, Browser wird geschlossen. Session gespeichert in {cfg['userdata']}")
        context.close()


@app.post("/session/init")
def session_init(req: DownloadRequest, request: Request):
    import threading

    if not check_debug_mode():
        raise HTTPException(
            status_code=400,
            detail="Debug-Modus nicht aktiv. Erst POST /debug/enable aufrufen."
        )

    site = req.site.strip().lower()
    if site not in ("freenet", "netaachen", "lexware"):
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
    if not check_debug_mode():
        return {"status": "already_disabled", "message": "Debug mode is already inactive"}
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
    matches = glob.glob("/var/log/supervisor/fastapi-stdout---supervisor-*.log")
    return matches[0] if matches else None

@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket, api_key: str = ""):
    if API_KEY and api_key != API_KEY:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    log_path = find_log_file()

    if not log_path:
        await websocket.send_text("⚠️  Log-Datei nicht gefunden")
        await websocket.close()
        return

    try:
        proc = await asyncio.create_subprocess_exec(
            "tail", "-n", "50", log_path,
            stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        for line in stdout.decode(errors="replace").splitlines():
            await websocket.send_text(line)

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
