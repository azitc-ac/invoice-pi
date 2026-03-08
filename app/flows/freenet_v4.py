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

LOGIN_URL = "https://www.freenet-mobilfunk.de/onlineservice/meine-rechnungen"

GER_MONTHS = [
    "Januar","Februar","März","April","Mai","Juni",
    "Juli","August","September","Oktober","November","Dezember"
]

def pick_latest_month(page):
    """Suche nach Monats-Tile und klicke auf den letzten (neuesten)"""
    # Versuche zuerst mit Jahreszahl
    month_regex = "(" + "|".join(GER_MONTHS) + r")\s+20\d{2}"
    tiles = page.locator(f"text=/{month_regex}/i")
    
    log(f"Suche Monate mit Regex '{month_regex}': {tiles.count()} gefunden", "DEBUG")
    
    if tiles.count() > 0:
        # Klicke auf den LETZTEN (neuesten) Monat
        tiles.last.click()
        log(f"Klicke auf letzten Monat (Index {tiles.count()-1})", "DEBUG")
        return True
    
    # Fallback: Suche nur nach Monatsnamen ohne Jahrzahl
    log("Kein Monat mit Jahrzahl gefunden, versuche ohne Jahrzahl...", "DEBUG")
    month_pattern = "|".join(GER_MONTHS)
    tiles = page.locator(f"text=/{month_pattern}/i")
    
    log(f"Suche Monate ohne Jahr: {tiles.count()} gefunden", "DEBUG")
    
    if tiles.count() > 0:
        tiles.last.click()
        log(f"Klicke auf letzten Monat (fallback)", "DEBUG")
        return True
    
    log("FEHLER: Keine Monate gefunden!", "ERROR")
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
        
        # Screenshot für Debugging
        page.screenshot(path=f"{download_dir}/freenet-01-login-page.png")
        
        time.sleep(2)  # Warte auf JavaScript-Rendering

        log("Fülle Credentials ein...")
        page.fill("#username", FR_USER)
        page.fill("#password", FR_PASS)
        
        time.sleep(1)
        page.screenshot(path=f"{download_dir}/freenet-03-credentials-filled.png")

        # WICHTIG: Versuche Cloudflare Captcha-Checkbox zu klicken BEVOR Login
        log("Suche nach Captcha-Checkbox...", "DEBUG")
        try:
            # Cloudflare Challenge Checkbox
            captcha_checkbox = page.locator("input[type='checkbox']")
            if captcha_checkbox.count() > 0:
                log(f"Captcha-Checkbox gefunden ({captcha_checkbox.count()}), klicke sie...", "DEBUG")
                captcha_checkbox.first.click(timeout=5000)
                time.sleep(3)  # Warte auf Captcha-Verarbeitung
                page.screenshot(path=f"{download_dir}/freenet-03b-captcha-clicked.png")
        except Exception as e:
            log(f"Captcha-Suche fehlgeschlagen (ok wenn nicht vorhanden): {str(e)[:60]}", "DEBUG")

        # Cookies akzeptieren (NACH Captcha)
        accept_cookies_hard(page)
        time.sleep(1)
        page.screenshot(path=f"{download_dir}/freenet-02-after-cookies.png")

        # Jetzt versuche Login
        log("Versuche Login mit XPath...")
        try:
            page.locator("//button[contains(., 'Anmelden')]").wait_for(state="visible", timeout=10000)
            page.screenshot(path=f"{download_dir}/freenet-04-before-click.png")
            
            # Normaler Click (jetzt sollte Button nicht mehr disabled sein)
            page.locator("//button[contains(., 'Anmelden')]").click(timeout=10000)
            log("Login-Button geklickt", "DEBUG")
        except Exception as e:
            log(f"XPath-Click fehlgeschlagen: {str(e)[:80]}", "ERROR")
            raise

        time.sleep(3)
        page.screenshot(path=f"{download_dir}/freenet-05-after-login.png")

        wait_network_idle(page, timeout_ms=30000)
        time.sleep(2)

        log("Suche Monatseintrag...")
        page.screenshot(path=f"{download_dir}/freenet-05-before-month-search.png")
        
        if not pick_latest_month(page):
            page.screenshot(path=f"{download_dir}/freenet-error-no-month.png")
            # Gib den HTML-Dump für Debugging aus
            page_content = page.content()
            with open(f"{download_dir}/freenet-error-page-html.txt", "w") as f:
                f.write(page_content)
            log("HTML-Dump gespeichert für Debugging", "DEBUG")
            raise RuntimeError("Konnte keinen Monatseintrag finden – Seite verändert?")

        time.sleep(2)
        page.screenshot(path=f"{download_dir}/freenet-06-month-selected.png")

        log("Suche PDF-Link...")
        with page.expect_download() as dl_info:
            if not click_top_pdf(page):
                page.screenshot(path=f"{download_dir}/freenet-error-no-pdf.png")
                raise RuntimeError("Konnte keinen PDF-Link finden.")
        
        download = dl_info.value
        out_file = save_download(download, download_dir)

        page.screenshot(path=f"{download_dir}/freenet-07-downloaded.png")
        ctx.close()
        return [out_file]
