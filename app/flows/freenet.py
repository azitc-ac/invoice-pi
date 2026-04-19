import os
import time
import subprocess
from playwright.sync_api import sync_playwright

FR_USER      = os.getenv("FREENET_USERNAME")
FR_PASS      = os.getenv("FREENET_PASSWORD")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/downloads")
PW_USERDATA  = os.getenv("PW_USERDATA_FREENET", "/pwdata/freenet")
CHROMIUM_BIN = os.getenv("CHROMIUM_BIN", "/ms-playwright/chromium-1208/chrome-linux/chrome")
CDP_PORT     = 9225

LOGIN_URL = "https://www.freenet-mobilfunk.de/onlineservice/meine-rechnungen"

GER_MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]

MONTH_MAP = {
    "Januar": "01", "Februar": "02", "März": "03", "April": "04",
    "Mai": "05", "Juni": "06", "Juli": "07", "August": "08",
    "September": "09", "Oktober": "10", "November": "11", "Dezember": "12",
}


def _dismiss_cookie_banner(page, total_wait=10):
    """Wartet bis zu total_wait Sekunden auf Cookie-Banner und klickt ihn weg.

    Freenet nutzt Sourcepoint — der Banner liegt in einem sp_message_iframe,
    nicht direkt auf der Seite. Daher wird zuerst in Iframes gesucht.
    """
    # Sourcepoint / Freenet: Banner in einem Consent-Iframe
    iframe_selectors = [
        "iframe[id^='sp_message_iframe']",
        "iframe[title='SP Consent Message']",
        "iframe[title*='Consent']",
        "iframe[title*='Datenschutz']",
        "iframe[src*='privacy-mgmt']",
    ]
    button_selectors = [
        "button:has-text('Alle akzeptieren')",
        "button:has-text('Akzeptieren')",
        "button:has-text('Zustimmen')",
        "button:has-text('Einverstanden')",
        "button#onetrust-accept-btn-handler",
        "button.onetrust-accept-btn-handler",
        "button:has-text('Accept all')",
        "button:has-text('Accept')",
        "[id*='accept'][id*='cookie']",
        "[class*='accept'][class*='cookie']",
    ]
    deadline = time.time() + total_wait
    while time.time() < deadline:
        # Zuerst in SP-Iframes suchen (Freenet / Sourcepoint)
        for iframe_sel in iframe_selectors:
            try:
                frame = page.frame_locator(iframe_sel)
                for btn_sel in button_selectors:
                    try:
                        btn = frame.locator(btn_sel).first
                        if btn.is_visible(timeout=500):
                            btn.click()
                            print(f"🍪 Cookie-Banner (iframe) weggeklickt ({btn_sel})")
                            time.sleep(1)
                            return
                    except Exception:
                        continue
            except Exception:
                continue
        # Fallback: direkt auf der Seite (OneTrust / NetAachen)
        for sel in button_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=300):
                    btn.click()
                    print(f"🍪 Cookie-Banner weggeklickt ({sel})")
                    time.sleep(1)
                    return
            except Exception:
                continue
        time.sleep(0.5)
    print("ℹ️ Kein Cookie-Banner gefunden")


def _handle_cloudflare(page, timeout=60):
    """Aktiviert Cloudflare Turnstile per Tastatur (Tab×4 + Space).

    Wartet zuerst bis der Spinner fertig ist und die Checkbox erscheint.
    Strategie: Frame erkennen, dann auf Submit-Button-Aktivierung warten
    (auto-solve). Bleibt er disabled, ist die Checkbox sichtbar → Tab×4+Space.
    """
    print("🛡️ Prüfe auf Cloudflare-Challenge...")
    deadline = time.time() + timeout

    # Phase 1: Warten bis Turnstile-Frame erscheint
    while time.time() < deadline:
        if any("challenges.cloudflare.com" in f.url for f in page.frames):
            print("  Turnstile-Frame erkannt, warte auf Checkbox (Spinner läuft)...")
            break
        time.sleep(0.5)
    else:
        print("ℹ️ Keine Cloudflare-Challenge erkannt")
        return False

    # Phase 2: Warten ob Turnstile auto-löst (Submit-Button wird enabled)
    # Gleichzeitig: wenn nach 30s noch disabled → Checkbox muss sichtbar sein
    wait_deadline = min(time.time() + 35, deadline)
    while time.time() < wait_deadline:
        try:
            btn = page.locator("button[type='submit']")
            if btn.get_attribute("disabled", timeout=500) is None:
                print("✅ Turnstile auto-gelöst, Submit-Button aktiv")
                return True
        except Exception:
            pass
        time.sleep(1)

    # Phase 3: Checkbox sollte jetzt sichtbar sein → Tab×4 + Space
    print("  Spinner fertig → Tab×4 + Space")
    for _ in range(4):
        page.keyboard.press("Tab")
        time.sleep(0.3)
    page.keyboard.press("Space")
    time.sleep(2)
    print("✅ Turnstile per Tastatur aktiviert")
    return True


def _login(page):
    """Füllt Login-Formular aus und wartet auf erfolgreichen Redirect."""
    print("🔐 Warte auf Login-Formular...")
    try:
        page.wait_for_selector("input#username, input[name='username']", timeout=15000)
        page.fill("input#username", FR_USER or "")
        page.fill("input#password", FR_PASS or "")
        print("✅ Credentials ausgefüllt")
    except Exception as e:
        raise RuntimeError(f"Login-Formular nicht gefunden: {e}")

    _handle_cloudflare(page)

    try:
        print("⏳ Warte auf aktivierten Submit-Button...")
        page.wait_for_selector("button[type='submit']:not([disabled])", timeout=15000)
        page.click("button[type='submit']", timeout=5000)
    except Exception as e:
        print(f"⚠️ Submit-Button: {e}")

    print("⏳ Warte auf erfolgreichen Login...")
    try:
        page.wait_for_function(
            "() => !window.location.href.includes('login') "
            "   && !window.location.href.includes('id.freenet')",
            timeout=30000,
        )
        print(f"✅ Login erfolgreich: {page.url}")
    except Exception as e:
        raise RuntimeError(f"Login fehlgeschlagen oder Timeout: {e}")
    time.sleep(2)


def pick_month(page, month_offset=0):
    month_regex = "(" + "|".join(GER_MONTHS) + r")\s+20\d{2}"
    tiles = page.locator(f"text=/{month_regex}/i")
    count = tiles.count()
    print(f"🔍 Suche Monate: {count} gefunden, offset={month_offset}")
    if count > month_offset:
        tile = tiles.nth(month_offset)
        month_text = tile.text_content().strip()
        tile.click()
        print(f"✅ Klicke auf Monat [{month_offset}]: {month_text}")
        return month_text
    print(f"❌ Monat mit offset={month_offset} nicht gefunden!")
    return None


def month_text_to_date_str(month_text):
    try:
        parts = month_text.strip().split()
        return f"{parts[1]}-{MONTH_MAP.get(parts[0], '00')}"
    except Exception:
        return "0000-00"


def click_top_pdf(page):
    print("🔍 Suche PDF-Links...")
    pdflinks = page.get_by_text("PDF")
    count = pdflinks.count()
    print(f"📝 Gefunden: {count} PDF-Links")
    if count == 0:
        return False
    pdf_positions = []
    for i in range(count):
        try:
            bbox = pdflinks.nth(i).bounding_box()
            if bbox:
                pdf_positions.append({"locator": pdflinks.nth(i), "y": bbox["y"]})
        except Exception:
            pass
    if not pdf_positions:
        return False
    top = sorted(pdf_positions, key=lambda x: x["y"])[0]
    try:
        top["locator"].scroll_into_view_if_needed()
        time.sleep(1)
        top["locator"].click(timeout=5000)
        print("✅ PDF-Link geklickt!")
        return True
    except Exception as e:
        print(f"❌ Click-Fehler: {e}")
        return False


def run_freenet_download(headless=True, month_offset=0):
    """Freenet Download mit frischem Login via CDP (Cloudflare-kompatibel).

    Läuft immer auf DISPLAY=:0 (Xvfb) — kein --headless, da Cloudflare
    headless Browser erkennt und blockiert.
    """
    print(f"\n🚀 Starte Freenet Download (CDP, fresh login, offset={month_offset})")

    for lock_file in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        lock_path = os.path.join(PW_USERDATA, lock_file)
        if os.path.lexists(lock_path):
            os.remove(lock_path)
            print(f"🧹 Lock entfernt: {lock_path}")

    subprocess.run(
        f"pkill -f 'remote-debugging-port={CDP_PORT}' 2>/dev/null",
        shell=True,
    )
    time.sleep(1)

    # Start a dedicated Xvfb on :2 with -ac (no auth) for Chromium.
    # The supervisord Xvfb on :0 was started without -ac, so Chromium's
    # Ozone X11 backend can't authenticate. :2 is our private display.
    chromium_display = ":2"
    subprocess.Popen(
        f"pkill -f 'Xvfb {chromium_display}' 2>/dev/null; "
        f"Xvfb {chromium_display} -screen 0 1280x900x24 -ac",
        shell=True,
    )
    time.sleep(1)
    if os.path.exists(f"/tmp/.X11-unix/X{chromium_display.lstrip(':')}"):
        print(f"✅ Eigener Xvfb auf DISPLAY={chromium_display}")
    else:
        print(f"⚠️ Xvfb auf {chromium_display} nicht bereit, falle auf :0 zurück")
        chromium_display = ":0"

    env = {**os.environ, "DISPLAY": chromium_display}

    # Start window manager via shell — no exception if fluxbox is absent
    subprocess.Popen(
        f"fluxbox -display {chromium_display}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    time.sleep(2)

    chromium_bin = CHROMIUM_BIN
    if not os.path.exists(chromium_bin):
        result = subprocess.run(
            "find /ms-playwright -name 'chrome' -type f 2>/dev/null | head -1",
            shell=True, capture_output=True, text=True,
        )
        found = result.stdout.strip()
        if found:
            chromium_bin = found
            print(f"🔍 Chromium gefunden (abweichender Pfad): {chromium_bin}")
        else:
            raise RuntimeError(f"Chromium Binary nicht gefunden: {chromium_bin} (kein Fallback)")
    print(f"🖥️ Starte Chromium: {chromium_bin}")

    import tempfile
    _stderr_tmp = tempfile.NamedTemporaryFile(delete=False, suffix="-chromium.log")
    _stderr_tmp.close()

    proc = subprocess.Popen(
        [
            chromium_bin,
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--ozone-platform=x11",
            "--disable-blink-features=AutomationControlled",
            "--user-agent=Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            "--lang=de-DE",
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={PW_USERDATA}",
            "--window-size=1280,900",
        ],
        stdout=subprocess.DEVNULL,
        stderr=open(_stderr_tmp.name, "w"),
        env=env,
    )
    print(f"🖥️ Chromium gestartet (PID={proc.pid})")
    time.sleep(3)

    try:
        exit_code = proc.poll()
        if exit_code is not None:
            try:
                with open(_stderr_tmp.name) as f:
                    stderr_tail = f.read()[-1500:].strip()
            except Exception:
                stderr_tail = "(stderr nicht lesbar)"
            finally:
                try:
                    os.unlink(_stderr_tmp.name)
                except Exception:
                    pass
            print(f"❌ Chromium sofort beendet (exit={exit_code}):\n{stderr_tail}", flush=True)
            raise RuntimeError(f"Chromium sofort beendet (exit={exit_code})")
        try:
            os.unlink(_stderr_tmp.name)
        except Exception:
            pass
        print(f"✅ Chromium läuft (PID={proc.pid}), verbinde CDP...")
        with sync_playwright() as p:
            try:
                browser = p.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
            except Exception as e:
                raise RuntimeError(f"CDP-Verbindung auf Port {CDP_PORT} fehlgeschlagen: {e}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            print(f"📖 Navigiere zu {LOGIN_URL}")
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            # JS-Redirect zu id.freenet.de abwarten
            try:
                page.wait_for_url(
                    lambda url: "id.freenet" in url or "meine-rechnungen" in url,
                    timeout=15000,
                )
            except Exception:
                pass

            current_url = page.url
            print(f"📍 URL nach Navigation: {current_url}")

            login_indicators = ["login", "signin", "auth", "id.freenet.de"]
            if any(x in current_url.lower() for x in login_indicators):
                print("🔐 Login erforderlich...")
                _login(page)
            else:
                print("✅ Bereits eingeloggt (Session noch aktiv)")

            # Cookie-Banner: erscheint erst nach vollständigem JS-Rendering
            print("🍪 Warte auf Cookie-Banner...")
            _dismiss_cookie_banner(page, total_wait=10)

            page.screenshot(path=f"{DOWNLOAD_DIR}/freenet-01-logged-in.png")

            print("\n📅 Suche Monatseintrag...")
            month_text = pick_month(page, month_offset=month_offset)
            if not month_text:
                page.screenshot(path=f"{DOWNLOAD_DIR}/freenet-error-no-month.png")
                raise RuntimeError("Konnte keinen Monatseintrag finden!")

            date_str = month_text_to_date_str(month_text)
            print(f"📅 Datums-String: {date_str}")
            time.sleep(5)
            page.screenshot(path=f"{DOWNLOAD_DIR}/freenet-02-month.png")

            print("\n📥 Starte PDF-Download...")
            with page.expect_download() as dl_info:
                if not click_top_pdf(page):
                    page.screenshot(path=f"{DOWNLOAD_DIR}/freenet-error-no-pdf.png")
                    raise RuntimeError("Konnte keinen PDF-Link finden!")

            download = dl_info.value
            filename = f"Rechnung_Freenet_{date_str}.pdf"
            path = os.path.join(DOWNLOAD_DIR, filename)
            download.save_as(path)
            print(f"✅ PDF gespeichert: {path}")

            page.screenshot(path=f"{DOWNLOAD_DIR}/freenet-03-done.png")
            browser.close()
            return [path]

    finally:
        proc.terminate()
        print("✅ Chromium beendet")


