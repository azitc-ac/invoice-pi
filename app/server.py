from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse, StreamingResponse
import json as _json
from pydantic import BaseModel
from typing import List, Optional
from contextlib import asynccontextmanager
from flows.freenet import run_freenet_download, run_freenet_keepalive
from flows.netaachen import run_netaachen_download, run_netaachen_keepalive
from flows.lexware import run_lexware_upload
from flows.analyze import analyze_invoice, _extract_text_both
import os
import subprocess
import time
import asyncio
import glob
import shutil
import tempfile
import traceback
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()

async def _scheduled_freenet_keepalive():
    print("⏰ Geplanter Freenet Keep-Alive gestartet (08:00)")
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_freenet_keepalive)
        print("✅ Geplanter Freenet Keep-Alive erfolgreich")
    except Exception as e:
        print(f"⚠️ Geplanter Freenet Keep-Alive fehlgeschlagen: {e}")

async def _scheduled_netaachen_keepalive():
    print("⏰ Geplanter NetAachen Keep-Alive gestartet (08:00)")
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_netaachen_keepalive)
        print("✅ Geplanter NetAachen Keep-Alive erfolgreich")
    except Exception as e:
        print(f"⚠️ Geplanter NetAachen Keep-Alive fehlgeschlagen: {e}")

@asynccontextmanager
async def lifespan(app):
    scheduler.add_job(_scheduled_freenet_keepalive, CronTrigger(hour=8, minute=0))
    scheduler.add_job(_scheduled_netaachen_keepalive, CronTrigger(hour=8, minute=5))
    scheduler.start()
    print("⏰ Scheduler gestartet — Keep-Alive täglich um 08:00 (Freenet) und 08:05 (NetAachen)")
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

lexware_lock = asyncio.Lock()

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
    save_session: bool = True


# ============================================================
# API ENDPOINT - Cleanup Locks
# ============================================================

PW_USERDIRS = {
    "freenet": os.getenv("PW_USERDATA_FREENET", "/pwdata/freenet"),
    "netaachen": os.getenv("PW_USERDATA_NETAACHEN", "/pwdata/netaachen"),
    "lexware": os.getenv("PW_USERDATA_LEXWARE", "/pwdata/lexware"),
}
FF_PROFILE_LEXWARE = os.getenv("FF_PROFILE_LEXWARE", "/pwdata/lexware-ff")
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

def _ensure_display_services():
    """Startet Xvfb, fluxbox, x11vnc und noVNC falls nicht aktiv."""
    for svc in ["xvfb", "fluxbox", "x11vnc", "novnc"]:
        if not get_supervisor_status(svc):
            try:
                import subprocess
                subprocess.run(f"supervisorctl start {svc}", shell=True, capture_output=True)
            except Exception:
                pass

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
        try:
            files = run_freenet_download(headless=is_headless(), month_offset=req.month_offset)
        except RuntimeError as e:
            if "SESSION_EXPIRED" in str(e):
                print(f"⚠️  SESSION_EXPIRED: Freenet — {e}")
            raise
        return {"status": "ok", "site": "freenet", "files": files}
    elif site == "netaachen":
        try:
            files = run_netaachen_download(headless=is_headless(), month_offset=req.month_offset)
        except RuntimeError as e:
            if "SESSION_EXPIRED" in str(e):
                print(f"⚠️  SESSION_EXPIRED: NetAachen — {e}")
            raise
        return {"status": "ok", "site": "netaachen", "files": files}
    else:
        raise HTTPException(status_code=400, detail="Unsupported site")

@app.post("/download/file")
def download_file(req: DownloadRequest):
    site = req.site.strip().lower()
    if site == "freenet":
        try:
            files = run_freenet_download(headless=is_headless())
        except RuntimeError as e:
            if "SESSION_EXPIRED" in str(e):
                print(f"⚠️  SESSION_EXPIRED: Freenet — {e}")
            raise
    elif site == "netaachen":
        try:
            files = run_netaachen_download(headless=is_headless())
        except RuntimeError as e:
            if "SESSION_EXPIRED" in str(e):
                print(f"⚠️  SESSION_EXPIRED: NetAachen — {e}")
            raise
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
async def upload_lexware(
    request: Request,
    filename: str = Query(default="upload.pdf")
):
    """
    Nimmt eine PDF als rohen Binary-Body entgegen und lädt sie via Playwright zu Lexware hoch.
    Query-Parameter: filename (optional, default: upload.pdf)
    Header: Content-Type: application/pdf
    """
    content = await request.body()
    if not content:
        raise HTTPException(status_code=400, detail="Kein Inhalt")

    safe_name = os.path.basename(filename)
    tmp_path = os.path.join(UPLOAD_DIR, safe_name)

    try:
        with open(tmp_path, "wb") as f:
            f.write(content)
        print(f"📥 Datei empfangen: {tmp_path} ({len(content)} bytes)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Speichern: {e}")

    if lexware_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="Ein Upload läuft bereits. Bitte warten und erneut versuchen."
        )

    async with lexware_lock:
        try:
            result = await run_lexware_upload(file_path=tmp_path, headless=is_headless())
            return result
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Upload fehlgeschlagen: {e}")


@app.post("/upload/lexware/path")
async def upload_lexware_by_path(req: dict):
    """
    Alternativer Endpoint: Lädt eine bereits lokal gespeicherte Datei zu Lexware hoch.
    Body: { "file_path": "/downloads/Rechnung_Freenet_2026-02.pdf" }
    """
    file_path = req.get("file_path", "").strip()
    if not file_path:
        raise HTTPException(status_code=400, detail="file_path fehlt")
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail=f"Datei nicht gefunden: {file_path}")

    if lexware_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="Ein Upload läuft bereits. Bitte warten und erneut versuchen."
        )

    async with lexware_lock:
        try:
            result = await run_lexware_upload(file_path=file_path, headless=is_headless())
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

def _open_browser_for_login(site: str, save_session: bool = True):
    """
    Öffnet Chromium via CDP (navigator.webdriver=false) für Session-Login.
    Freenet/NetAachen: Credentials vorausgefüllt, manuell Anmelden klicken.
    Lexware: manuell einloggen.
    Profil wird in userdata-Verzeichnis gespeichert.
    """
    import subprocess as _sp
    from playwright.sync_api import sync_playwright as _pw

    configs = {
        "freenet": {
            "url": "https://www.freenet-mobilfunk.de/onlineservice/meine-rechnungen",
            "userdata": os.getenv("PW_USERDATA_FREENET", "/pwdata/freenet"),
            "username": os.getenv("FREENET_USERNAME", ""),
            "password": os.getenv("FREENET_PASSWORD", ""),
            "fill_username": "input#username",
            "fill_password": "input#password",
            "login_done": lambda url: "login" not in url.lower() and "freenet" in url.lower(),
        },
        "netaachen": {
            "url": "https://sso.netcologne.de/cas/login?service=https://meinekundenwelt.netcologne.de/&mandant=na",
            "userdata": os.getenv("PW_USERDATA_NETAACHEN", "/pwdata/netaachen"),
            "username": os.getenv("NETAACHEN_USERNAME", ""),
            "password": os.getenv("NETAACHEN_PASSWORD", ""),
            "fill_username": "input#username",
            "fill_password": "input#password",
            "login_done": lambda url: "meinekundenwelt" in url.lower() and "cas/login" not in url.lower(),
        },
        "lexware": {
            "url": "https://app.lexware.de",
            "userdata": os.getenv("PW_USERDATA_LEXWARE", "/pwdata/lexware"),
            "username": os.getenv("LEXWARE_USERNAME", ""),
            "password": os.getenv("LEXWARE_PASSWORD", ""),
            "fill_username": None,
            "fill_password": None,
            "login_done": lambda url: "dashboard" in url.lower(),
        },
    }

    cfg = configs[site]
    cdp_port = 9224
    profile_dir = cfg["userdata"] + "-session-tmp"

    # Chromium starten mit CDP
    _sp.run(f"pkill -f 'remote-debugging-port={cdp_port}' 2>/dev/null", shell=True)
    time.sleep(1)

    import shutil as _shutil
    if os.path.exists(profile_dir):
        _shutil.rmtree(profile_dir)

    download_dir = os.getenv("DOWNLOAD_DIR", "/downloads")

    # Download-Ordner in Chrome-Preferences setzen BEVOR Chromium startet
    import json as _json_dl
    prefs_dir = os.path.join(profile_dir, "Default")
    os.makedirs(prefs_dir, exist_ok=True)
    prefs_path = os.path.join(prefs_dir, "Preferences")
    prefs = {}
    if os.path.exists(prefs_path):
        try: prefs = _json_dl.loads(open(prefs_path).read())
        except Exception: prefs = {}
    prefs.setdefault("download", {}).update({
        "default_directory": download_dir,
        "prompt_for_download": False,
        "directory_upgrade": True,
    })
    prefs.setdefault("savefile", {})["default_directory"] = download_dir
    open(prefs_path, "w").write(_json_dl.dumps(prefs))
    print(f"📂 Download-Ordner gesetzt: {download_dir}")

    print(f"🌐 Starte Chromium für {site} Session-Login...")
    proc = _sp.Popen([
        "/ms-playwright/chromium-1208/chrome-linux/chrome",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={profile_dir}",
        "--window-size=1280,900",
        cfg["url"],
    ], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)

    time.sleep(4)

    try:
        with _pw() as p:
            browser = p.chromium.connect_over_cdp(f"http://localhost:{cdp_port}")
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.bring_to_front()

            # Download-Ordner auf /downloads setzen
            try:
                ctx.pages[0]._impl_obj._channel.send("Browser.setDownloadBehavior", {
                    "behavior": "allow",
                    "downloadPath": download_dir,
                    "eventsEnabled": True,
                }) if False else None  # CDP-Methode via Playwright context
                await_result = browser._impl_obj._channel.send if False else None
            except Exception:
                pass
            # Playwright-native Methode
            try:
                for pg in ctx.pages:
                    pg.context.set_default_timeout(0)
            except Exception:
                pass
            # Chromium Preferences: Download-Pfad setzen
            import json as _json2
            prefs_path = os.path.join(profile_dir, "Default", "Preferences")
            os.makedirs(os.path.dirname(prefs_path), exist_ok=True)
            try:
                prefs = _json2.loads(open(prefs_path).read()) if os.path.exists(prefs_path) else {}
            except Exception:
                prefs = {}
            prefs.setdefault("download", {})["default_directory"] = download_dir
            prefs["download"]["prompt_for_download"] = False
            open(prefs_path, "w").write(_json2.dumps(prefs))
            print(f"📂 Download-Ordner: {download_dir}")

            time.sleep(3)
            print(f"🔍 navigator.webdriver: {page.evaluate('navigator.webdriver')}")
            print(f"📍 URL: {page.url}")

            # Cookie-Banner wegklicken
            js_cookie = """
function findAndClick(root) {
    var kw = ['alle akzept','akzept','zustimm','accept all','accept'];
    var tags = ['button','a','[role="button"]'];
    for (var ti=0;ti<tags.length;ti++){
        var els=root.querySelectorAll(tags[ti]);
        for (var i=0;i<els.length;i++){
            var txt=(els[i].innerText||els[i].textContent||'').toLowerCase().trim();
            for (var ki=0;ki<kw.length;ki++){if(txt.indexOf(kw[ki])!==-1){els[i].click();return true;}}
        }
    }
    return false;
}
return findAndClick(document);
"""
            deadline = time.time() + 8
            while time.time() < deadline:
                try:
                    if page.evaluate(js_cookie):
                        print("✅ Cookie-Banner geschlossen")
                        time.sleep(0.6)
                        break
                except Exception:
                    pass
                time.sleep(0.3)

            # Credentials vorausfüllen
            if cfg["fill_username"] and cfg["username"]:
                try:
                    page.wait_for_selector(cfg["fill_username"], timeout=10000)
                    page.fill(cfg["fill_username"], cfg["username"])
                    print(f"✅ Username vorausgefüllt")
                except Exception as e:
                    print(f"⚠️  Username: {e}")

            if cfg["fill_password"] and cfg["password"]:
                try:
                    page.fill(cfg["fill_password"], cfg["password"])
                    print(f"✅ Passwort vorausgefüllt")
                except Exception as e:
                    print(f"⚠️  Passwort: {e}")

            # Download-Events loggen
            def _on_download(dl):
                print(f"📥 Download gestartet: {dl.suggested_filename}")
                try:
                    dl.save_as(os.path.join(download_dir, dl.suggested_filename))
                    print(f"✅ Download gespeichert: {download_dir}/{dl.suggested_filename}")
                except Exception as e:
                    print(f"⚠️  Download-Fehler: {e}")
            page.on("download", _on_download)

            # Download-Events loggen
            def _on_download(dl):
                print(f"📥 Download gestartet: {dl.suggested_filename}")
                try:
                    dl.save_as(os.path.join(download_dir, dl.suggested_filename))
                    print(f"✅ Download gespeichert: {download_dir}/{dl.suggested_filename}")
                except Exception as e:
                    print(f"⚠️  Download-Fehler: {e}")
            page.on("download", _on_download)

            if cfg["fill_username"]:
                print(f"👉 Bitte jetzt auf Anmelden klicken!")
            else:
                print(f"👉 Bitte manuell einloggen (User: {cfg['username']})")

            timeout_sec = 3600 if not save_session else 600
            print(f"⏳ Warte auf Login (max {'60' if not save_session else '10'} Minuten)...")

            # Warten bis eingeloggt
            deadline = time.time() + timeout_sec
            logged_in = False
            while time.time() < deadline:
                try:
                    url = page.evaluate("window.location.href")
                    if cfg["login_done"](url):
                        logged_in = True
                        print(f"✅ Login erkannt! URL: {url}")
                        break
                except Exception:
                    pass
                time.sleep(5)

            if logged_in:
                if save_session:
                    print(f"⏳ Warte 15s damit Cookies gespeichert werden...")
                    time.sleep(15)
                    storage_path = os.path.join(cfg["userdata"], "playwright-storage.json")
                    os.makedirs(cfg["userdata"], exist_ok=True)
                    try:
                        ctx.storage_state(path=storage_path)
                        print(f"✅ Storage State gespeichert: {storage_path}")
                    except Exception as e:
                        print(f"⚠️  Storage State: {e}")
                else:
                    print(f"✅ Eingeloggt (ohne Session-Speicherung) — Browser bleibt offen...")
                    # Warten und dabei Downloads überwachen
                    import glob as _glob
                    known_files = set()
                    wait_end = time.time() + 3600
                    while time.time() < wait_end:
                        # Downloads aus Chrome-Profil nach /downloads kopieren
                        chrome_dl = os.path.join(profile_dir, "Default", "Downloads")
                        # Auch direkt im profile_dir suchen
                        for pattern in [
                            os.path.join(profile_dir, "*.pdf"),
                            os.path.join(profile_dir, "*.PDF"),
                            os.path.join(profile_dir, "Default", "*.pdf"),
                        ]:
                            for f_path in _glob.glob(pattern):
                                if f_path not in known_files and not f_path.endswith(".crdownload"):
                                    known_files.add(f_path)
                                    fname = os.path.basename(f_path)
                                    dest = os.path.join(download_dir, fname)
                                    try:
                                        import shutil as _sh
                                        _sh.copy2(f_path, dest)
                                        print(f"📥 Download kopiert: {fname} → {download_dir}")
                                    except Exception as e:
                                        print(f"⚠️  Kopieren fehlgeschlagen: {e}")
                        # Abbrechen wenn Browser geschlossen wurde
                        try:
                            _ = page.evaluate("1")
                        except Exception:
                            print(f"🔒 Browser geschlossen — Session-Modus beendet")
                            break
                        time.sleep(3)
            else:
                print(f"⚠️  Login-Timeout — Session nicht gespeichert")

            browser.close()

    finally:
        proc.terminate()
        print(f"✅ Browser geschlossen")


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

    thread = threading.Thread(target=_open_browser_for_login, args=(site, req.save_session), daemon=True)
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

@app.post("/keepalive/freenet")
async def keepalive_freenet():
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_freenet_keepalive)
        return {"status": "ok", "message": "Freenet Session erfolgreich aktualisiert"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/keepalive/netaachen")
async def keepalive_netaachen():
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_netaachen_keepalive)
        return {"status": "ok", "message": "NetAachen Session erfolgreich aktualisiert"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
# Analyse-Endpoint
# ============================================================

@app.post("/analyze/invoice")
async def analyze_invoice_endpoint(
    file: UploadFile = File(...),
    debug: bool = Query(False),
):
    """PDF hochladen und Rechnungsdaten extrahieren.
    Verwendet Streaming-Keep-Alive damit iOS Safari bei langen OCR-Läufen
    die Verbindung nicht abbricht. Mit ?debug=true wird Rohtext zurückgegeben."""
    content = await file.read()
    original_filename = file.filename
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    async def _stream():
        try:
            loop = asyncio.get_event_loop()
            future = asyncio.ensure_future(
                loop.run_in_executor(None, analyze_invoice, tmp_path)
            )
            # Keep-Alive: alle 20s ein Leerzeichen senden damit Safari nicht abbricht
            while not future.done():
                try:
                    await asyncio.wait_for(asyncio.shield(future), timeout=20.0)
                except asyncio.TimeoutError:
                    yield b' '

            result = future.result()
            result["original_filename"] = original_filename
            result.pop("raw_text_preview", None)
            print(f"📋 Rechnung analysiert: {result.get('suggested_filename', '?')} | Datum: {result.get('invoice_date', '?')} | Betrag: {result.get('amount', '?')}")
            if debug:
                plumber_text, ocr_text = await loop.run_in_executor(
                    None, _extract_text_both, tmp_path
                )
                result["debug_pdfplumber"] = plumber_text[:3000]
                result["debug_ocr"] = ocr_text[:3000]
            yield _json.dumps(result, ensure_ascii=False).encode()
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    return StreamingResponse(_stream(), media_type="application/json")


# ============================================================
# File download endpoint
# ============================================================

@app.get("/downloads/file")
async def download_file_by_path(path: str, request: Request):
    """Einzelne Datei aus /downloads herunterladen."""
    download_dir = os.getenv("DOWNLOAD_DIR", "/downloads")
    # Sicherheit: nur Dateien im DOWNLOAD_DIR erlauben
    abs_path = os.path.realpath(path)
    abs_dir  = os.path.realpath(download_dir)
    if not abs_path.startswith(abs_dir):
        raise HTTPException(status_code=403, detail="Zugriff verweigert")
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    return FileResponse(abs_path, filename=os.path.basename(abs_path))


# ============================================================

def find_log_file() -> str | None:
    fixed = "/var/log/supervisor/fastapi-stdout.log"
    if os.path.isfile(fixed):
        return fixed
    # Fallback: alter Supervisor-Auto-Name (z.B. nach Image-Rebuild vor erstem Neustart)
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
        from datetime import datetime

        def ts(line: str) -> str:
            """Zeitstempel prependen falls Zeile nicht leer."""
            line = line.strip()
            if not line:
                return line
            return f"{datetime.now().strftime('%Y-%m-%d_%H:%M:%S')} - {line}"

        proc = await asyncio.create_subprocess_exec(
            "tail", "-n", "50", log_path,
            stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        for line in stdout.decode(errors="replace").splitlines():
            await websocket.send_text(ts(line))

        proc = await asyncio.create_subprocess_exec(
            "tail", "-f", "-n", "0", log_path,
            stdout=asyncio.subprocess.PIPE
        )

        while True:
            line = await proc.stdout.readline()
            if not line:
                await asyncio.sleep(0.1)
                continue
            await websocket.send_text(ts(line.decode(errors="replace").rstrip()))

    except WebSocketDisconnect:
        proc.terminate()
    except Exception as e:
        await websocket.send_text(f"❌ Log-Stream-Fehler: {e}")
        await websocket.close()
