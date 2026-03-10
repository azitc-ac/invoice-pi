from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from typing import List
from flows.freenet import run_freenet_download
from flows.netaachen import run_netaachen_download
import os
import subprocess
import time

app = FastAPI()

# ============================================================
# API KEY MIDDLEWARE
# ============================================================

API_KEY = os.getenv("API_KEY", "")

@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    # Health-Endpoint ist immer offen (z.B. für App Proxy Health-Check)
    if request.url.path == "/health":
        return await call_next(request)

    # Kein API_KEY konfiguriert → Warnung, aber durchlassen (Dev-Modus)
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

# ============================================================
# API ENDPOINTS - Download
# ============================================================

@app.post("/download")
def download(req: DownloadRequest):
    """Trigger Download, gibt Dateipfade zurück (lokale Speicherung)"""
    site = req.site.strip().lower()
    if site == "freenet":
        files = run_freenet_download()
        return {"status": "ok", "site": "freenet", "files": files}
    elif site == "netaachen":
        files = run_netaachen_download()
        return {"status": "ok", "site": "netaachen", "files": files}
    else:
        raise HTTPException(status_code=400, detail="Unsupported site")

@app.post("/download/file")
def download_file(req: DownloadRequest):
    """Trigger Download und liefere die PDF-Datei direkt zurück (für Power Automate)"""
    site = req.site.strip().lower()
    if site == "freenet":
        files: List[str] = run_freenet_download()
    elif site == "netaachen":
        files: List[str] = run_netaachen_download()
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
# API ENDPOINTS - Health & Debug
# ============================================================

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/debug/status")
def debug_status():
    """Check debug mode status"""
    is_enabled = check_debug_mode()
    
    return {
        "debug_enabled": is_enabled,
        "vnc_url": "http://192.168.1.125:8081/vnc.html" if is_enabled else None,
        "services": {
            "xvfb": get_supervisor_status("xvfb"),
            "fluxbox": get_supervisor_status("fluxbox"),
            "x11vnc": get_supervisor_status("x11vnc"),
            "novnc": get_supervisor_status("novnc"),
            "fastapi": get_supervisor_status("fastapi"),
        }
    }

@app.post("/debug/enable")
def debug_enable():
    """Enable debug mode (start VNC services)"""
    
    if check_debug_mode():
        return {
            "status": "already_enabled",
            "message": "Debug mode is already active",
            "vnc_url": "http://192.168.1.125:8081/vnc.html"
        }
    
    print("🚀 Starting VNC services...")
    results = start_vnc_services()
    
    time.sleep(3)
    
    is_enabled = check_debug_mode()
    
    return {
        "status": "enabled" if is_enabled else "partial",
        "message": "Debug mode activated - VNC services started",
        "vnc_url": "http://192.168.1.125:8081/vnc.html" if is_enabled else None,
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
