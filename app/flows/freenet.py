import os
import re
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

        page.fill("#username", FR_USER)
        page.fill("#password", FR_PASS)
        page.get_by_role("button", name=re.compile("Anmelden", re.I)).click()

        wait_network_idle(page)
        accept_cookies_hard(page)
        page.wait_for_timeout(500)
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
