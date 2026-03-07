import os
import time
from pathlib import Path
from playwright.sync_api import Page, BrowserContext

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/downloads")

def log(msg: str, level: str = "INFO"):
    levels = ["DEBUG", "INFO", "WARN", "ERROR"]
    if levels.index(level) >= levels.index(LOG_LEVEL):
        print(f"[{level}] {msg}", flush=True)

def ensure_dirs():
    Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)

def _env_headless() -> bool:
    return os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes", "on")

def launch_persistent(p, user_data_dir: str) -> BrowserContext:
    ensure_dirs()
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=_env_headless(),
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--window-size=1280,900",
        ],
        accept_downloads=True,
    )
    return ctx

def accept_cookies_easy(page: Page):
    try:
        loc = page.locator("a:has-text('Alle akzeptieren')")
        if loc.count():
            loc.first.click(timeout=3000)
            log("Cookie-Banner (easy) akzeptiert.", "DEBUG")
    except Exception:
        pass

def accept_cookies_hard(page: Page):
    iframe_selectors = [
        "iframe[title*='Consent']",
        "iframe[title*='Datenschutz']",
        "iframe[title='SP Consent Message']",
        "iframe[id^='sp_message_iframe']",
        "iframe[src*='privacy-mgmt']",
    ]
    button_texts = ["Alle akzeptieren", "Akzeptieren", "Zustimmen", "Einverstanden"]
    try:
        for sel in iframe_selectors:
            frames = page.locator(sel)
            for i in range(frames.count()):
                frame_el = frames.nth(i)
                frame = frame_el.content_frame()
                if not frame:
                    continue
                for bt in button_texts:
                    try:
                        frame.get_by_role("button", name=bt).click(timeout=1000)
                        log("Cookie-Banner (hard) akzeptiert.", "DEBUG")
                        return
                    except Exception:
                        pass
    except Exception:
        pass

def wait_network_idle(page: Page, timeout_ms: int = 15000):
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        time.sleep(1)

def save_download(download, target_dir: str) -> str:
    Path(target_dir).mkdir(parents=True, exist_ok=True)
    fn = download.suggested_filename
    out_path = os.path.join(target_dir, fn)
    download.save_as(out_path)
    log(f"Download gespeichert: {out_path}")
    return out_path
