import os
import time
from playwright.sync_api import sync_playwright
from common import (
    log, launch_persistent, accept_cookies_easy, wait_network_idle, save_download
)

NET_USER = os.getenv("NETAACHEN_USERNAME")
NET_PASS = os.getenv("NETAACHEN_PASSWORD")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/downloads")
PW_USERDATA = os.getenv("PW_USERDATA_NETAACHEN", "/pwdata/netaachen")

LOGIN_URL = "https://sso.netcologne.de/cas/login?service=https://meinekundenwelt.netcologne.de/&mandant=na"

def run_netaachen_download(download_dir: str = DOWNLOAD_DIR):
    with sync_playwright() as p:
        ctx = launch_persistent(p, PW_USERDATA)
        page = ctx.new_page()

        log(f"Gehe zu {LOGIN_URL}")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        
        time.sleep(2)
        page.screenshot(path=f"{download_dir}/netaachen-01-login-page.png")

        page.fill("#username", NET_USER)
        page.fill("#password", NET_PASS)
        
        time.sleep(1)
        page.screenshot(path=f"{download_dir}/netaachen-02-credentials-filled.png")
        
        # Nutze XPath wie bei Selenium
        page.locator("input[type='submit'][value='Anmelden']").click()

        time.sleep(3)
        page.screenshot(path=f"{download_dir}/netaachen-03-after-login.png")

        wait_network_idle(page, timeout_ms=30000)
        accept_cookies_easy(page)
        
        time.sleep(2)
        page.screenshot(path=f"{download_dir}/netaachen-04-after-cookies.png")

        log("Klicke auf 'Meine Rechnungen'")
        page.locator("xpath=//span[contains(text(), 'Meine Rechnungen')]").first.click(timeout=20000)
        
        time.sleep(2)
        page.screenshot(path=f"{download_dir}/netaachen-05-meine-rechnungen.png")

        wait_network_idle(page)
        
        log("Klicke auf 'Aktuelle Rechnung'")
        page.locator("xpath=//span[contains(text(), 'Aktuelle Rechnung')]").first.click(timeout=20000)
        
        time.sleep(2)
        page.screenshot(path=f"{download_dir}/netaachen-06-aktuelle-rechnung.png")

        wait_network_idle(page)
        
        log("Klicke auf 'Download'")
        page.locator("xpath=//span[contains(text(), 'Download')]").first.click(timeout=20000)

        time.sleep(2)
        page.screenshot(path=f"{download_dir}/netaachen-07-download-clicked.png")

        # Modal für PDF-Download
        modal = page.locator("[data-e2e='modal-billing-download-landline']")
        if not modal.count():
            modal = page.locator("div[role='dialog']")

        time.sleep(1)
        page.screenshot(path=f"{download_dir}/netaachen-08-modal-open.png")

        with page.expect_download() as dl_info:
            log("Klicke auf PDF in Modal")
            modal.locator("xpath=//*[contains(text(), 'PDF')]").first.click(timeout=10000)
        
        download = dl_info.value
        out_file = save_download(download, download_dir)

        page.screenshot(path=f"{download_dir}/netaachen-09-downloaded.png")
        ctx.close()
        return [out_file]
