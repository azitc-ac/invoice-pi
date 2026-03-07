from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.flows.freenet import run_freenet_download
from app.flows.netaachen import run_netaachen_download

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
