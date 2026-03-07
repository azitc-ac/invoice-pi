import os
import re
import time
from common import (
    log, launch_persistent, accept_cookies_hard, wait_network_idle, save_download
)
from playwright.sync_api import sync_playwright

FR_USER = os.getenv("FREENET_USERNAME")
FR_PASS = os.getenv("FREENET_PASSWORD")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/downloads")
PW_USERDATA = os.getenv("PW_USERDATA_FREENET", "/pwdata/freenet")
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes", "on")

LOGIN_URL = "https://www.freenet-mobilfunk.de/onlineservice/meine-rechnungen"

GER_MONTHS = [
    "Januar","Februar","März","April","Mai","Juni",
    "Juli","August","September","Oktober","November","Dezember"
]

def pick_latest_month(page):
    month_regex = "(" + "|".join(GER_MONTHS) + r")\s+20\d{2}"
    tiles = page.locator(f"text=/{month_regex}/i")
    if tiles.count():
        tiles.first.click()
        return True
    return False

def click_top_pdf(page):
    pdflinks = page.get_by_text("PDF", exact=False)
    if pdflinks.count():
        pdflinks.first.click()
        return True
    return False

def run_freenet_download(download_dir: str = DOWNLOAD_DIR):
    with sync_playwright() as p:
        ctx = launch_persistent(p, PW_USERDATA)
        page = ctx.new_page()

        log(f"Gehe zu {LOGIN_URL}")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        # Cookies früh akzeptieren
        accept_cookies_hard(page)
        page.wait_for_timeout(500)

        page.fill("#username", FR_USER)
        page.fill("#password", FR_PASS)
        
        # Versuche JavaScript zu nutzen um den Submit zu triggern (umgeht Captcha-Button-Check)
        submit_btn = page.get_by_role("button", name=re.compile("Anmelden", re.I))
        
        log("Versuche Login-Button zu klicken...", "DEBUG")
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                # Warte kurz auf Seite
                page.wait_for_timeout(2000)
                
                # Prüfe ob Button noch disabled ist
                is_disabled = page.evaluate(
                    "() => document.querySelector('button[type=submit]')?.disabled ?? true"
                )
                
                if is_disabled:
                    log(f"Button noch disabled (Versuch {attempt + 1}/{max_attempts}), warte...", "DEBUG")
                    if attempt == max_attempts - 1:
                        # Letzter Versuch: Force-Click mit JavaScript
                        log("Erzwinge Login mit JavaScript...", "WARN")
                        page.evaluate("""
                            () => {
                                const btn = document.querySelector('button[type=submit]');
                                if (btn) {
                                    btn.disabled = false;
                                    btn.click();
                                }
                            }
                        """)
                    continue
                
                # Button ist enabled, normaler Click
                submit_btn.click(timeout=5000)
                log("Login-Button erfolgreich geklickt!", "DEBUG")
                break
                
            except Exception as e:
                log(f"Click-Fehler Versuch {attempt + 1}: {str(e)[:60]}", "DEBUG")
                if attempt == max_attempts - 1:
                    raise

        wait_network_idle(page)
        page.wait_for_timeout(1000)
        
        # Nach Login: Check ob noch auf Login-Seite
        try:
            page.wait_for_url(lambda url: "meine-rechnungen" not in url, timeout=10000)
            log("Login erfolgreich, navigiere zu Rechnungen...", "DEBUG")
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
        except Exception as e:
            log(f"Login-Check fehlgeschlagen: {str(e)[:60]}", "WARN")

        wait_network_idle(page)

        if not pick_latest_month(page):
            raise RuntimeError("Konnte keinen Monatseintrag finden – Seite verändert?")

        with page.expect_download() as dl_info:
            if not click_top_pdf(page):
                raise RuntimeError("Konnte keinen PDF-Link finden.")
        download = dl_info.value
        out_file = save_download(download, download_dir)

        ctx.close()
        return [out_file]
