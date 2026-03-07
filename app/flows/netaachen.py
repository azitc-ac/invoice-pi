import os
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

        page.fill("#username", NET_USER)
        page.fill("#password", NET_PASS)
        page.locator("input[type='submit'][value='Anmelden']").click()

        wait_network_idle(page)
        accept_cookies_easy(page)

        # Nutze .first statt exact=False um strict mode zu vermeiden
        page.get_by_text("Meine Rechnungen").first.click(timeout=20000)
        wait_network_idle(page)
        page.get_by_text("Aktuelle Rechnung").first.click(timeout=20000)
        wait_network_idle(page)
        page.get_by_text("Download").first.click(timeout=20000)

        modal = page.locator("[data-e2e='modal-billing-download-landline']")
        if not modal.count():
            modal = page.locator("div[role='dialog']")

        with page.expect_download() as dl_info:
            modal.get_by_text("PDF", exact=False).first.click()
        download = dl_info.value
        out_file = save_download(download, download_dir)

        ctx.close()
        return [out_file]
