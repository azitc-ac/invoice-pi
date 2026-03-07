from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from flows.freenet_v3 import run_freenet_download
from flows.netaachen_v2 import run_netaachen_download
from fastapi.responses import FileResponse
import os

app = FastAPI()

class DownloadRequest(BaseModel):
    site: str

@app.post("/download")
def download(req: DownloadRequest):
    site = req.site.strip().lower()
    if site == "freenet":
        files = run_freenet_download()
        return {"status": "ok", "site": "freenet", "files": files}
    elif site == "netaachen":
        files = run_netaachen_download()
        return {"status": "ok", "site": "netaachen", "files": files}
    else:
        raise HTTPException(status_code=400, detail="Unsupported site")

@app.get("/health")
def health():
    return {"status": "ok"}

# --- NEU: streamt die Datei direkt zurück ---
@app.post("/download/file")
def download_file(req: DownloadRequest):
    site = req.site.strip().lower()
    if site == "freenet":
        files: List[str] = run_freenet_download()
    elif site == "netaachen":
        files: List[str] = run_netaachen_download()
    else:
        raise HTTPException(status_code=400, detail="Unsupported site")

    if not files:
        raise HTTPException(status_code=500, detail="No file downloaded")

    # Im Moment liefern die Flows je 1 Datei zurück; nimm die erste
    path = files[0]
    if not os.path.isfile(path):
        raise HTTPException(status_code=500, detail="Downloaded file not found")

    filename = os.path.basename(path)
    # Content-Type heuristisch nach Endung
    if filename.lower().endswith(".pdf"):
        media_type = "application/pdf"
    elif filename.lower().endswith(".zip"):
        media_type = "application/zip"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        path=path,
        media_type=media_type,
        filename=filename,  # setzt Content-Disposition mit korrektem Namen
    )