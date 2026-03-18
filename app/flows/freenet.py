import os
import time
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

MONTH_MAP = {
    "Januar": "01", "Februar": "02", "März": "03", "April": "04",
    "Mai": "05", "Juni": "06", "Juli": "07", "August": "08",
    "September": "09", "Oktober": "10", "November": "11", "Dezember": "12"
}

def pick_month(page, month_offset=0):
    """Wählt Monatseintrag aus. month_offset=0 → aktuellster, 1 → Vormonat usw."""
    month_regex = "(" + "|".join(GER_MONTHS) + r")\s+20\d{2}"
    tiles = page.locator(f"text=/{month_regex}/i")

    count = tiles.count()
    print(f"🔍 Suche Monate: {count} gefunden, offset={month_offset}")

    if count > month_offset:
        tile = tiles.nth(month_offset)
        month_text = tile.text_content().strip()
        tile.click()
        print(f"✅ Klicke auf Monat [{month_offset}]: {month_text}")
        return month_text  # z.B. "Februar 2026"

    print(f"❌ Monat mit offset={month_offset} nicht gefunden (nur {count} vorhanden)!")
    return None

def month_text_to_date_str(month_text):
    """'Februar 2026' → '2026-02'"""
    try:
        parts = month_text.strip().split()
        month_num = MONTH_MAP.get(parts[0], "00")
        return f"{parts[1]}-{month_num}"
    except Exception:
        return "0000-00"

def click_top_pdf(page):
    """Klicke auf obersten PDF-Link (nach Y-Position sortiert)"""
    print(f"🔍 Suche PDF-Links...")
    
    pdflinks = page.get_by_text("PDF")
    count = pdflinks.count()
    print(f"📝 Gefunden: {count} PDF-Links")
    
    if count == 0:
        print("❌ Keine PDF-Links gefunden!")
        return False
    
    pdf_positions = []
    for i in range(count):
        try:
            locator = pdflinks.nth(i)
            bbox = locator.bounding_box()
            if bbox:
                pdf_positions.append({
                    'locator': locator,
                    'y': bbox['y'],
                    'index': i
                })
                print(f"  Link {i}: Y={bbox['y']}")
        except:
            pass
    
    if not pdf_positions:
        print("❌ Konnte Y-Positionen nicht bestimmen!")
        return False
    
    top_pdf = sorted(pdf_positions, key=lambda x: x['y'])[0]
    print(f"✅ Wähle obersten PDF-Link (Y={top_pdf['y']})")
    
    try:
        top_pdf['locator'].scroll_into_view_if_needed()
        time.sleep(1)
        top_pdf['locator'].click(timeout=5000)
        print("✅ PDF-Link geklickt!")
        return True
    except Exception as e:
        print(f"❌ Fehler beim Click: {e}")
        return False

def save_download(download, download_dir, date_str):
    """Speichere Download mit sprechendem Dateinamen"""
    filename = f"Rechnung_Freenet_{date_str}.pdf"
    path = os.path.join(download_dir, filename)
    download.save_as(path)
    print(f"✅ PDF gespeichert: {path}")
    return path

def run_freenet_download(headless=True, month_offset=0):
    """
    Download Freenet Rechnungen via Playwright
    
    headless=False: Manuelles Einloggen + Session speichern (einmalig!)
    headless=True: Nutzt gespeicherte Session (automatisch)
    """
    
    print(f"\n🚀 Starte Playwright (headless={headless})")
    print(f"📁 User Data Dir: {PW_USERDATA}")

    # Stale Lock-Dateien entfernen (verhindert "profile in use" Fehler nach Absturz)
    for lock_file in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        lock_path = os.path.join(PW_USERDATA, lock_file)
        if os.path.exists(lock_path):
            os.remove(lock_path)
            print(f"\U0001f9f9 Lock-Datei entfernt: {lock_path}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PW_USERDATA,
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-setuid-sandbox",
            ]
        )
        
        # Storage State laden falls vorhanden
        import json as _json
        storage_path = os.path.join(PW_USERDATA, 'playwright-storage.json')
        if os.path.isfile(storage_path):
            try:
                with open(storage_path) as _f:
                    state = _json.load(_f)
                cookies = state.get('cookies', [])
                if cookies:
                    context.add_cookies(cookies)
                    print(f'✅ {len(cookies)} Session-Cookie(s) geladen')
            except Exception as e:
                print(f'⚠️  Storage State Fehler: {e}')

        page = context.new_page()
        
        # Anti-WebDriver-Detection
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false,
            });
        """)
        
        print(f"📖 Gehe zu {LOGIN_URL}")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        
        time.sleep(2)

        # Prüfen ob Session gültig ist (kein Login-Dialog)
        current_url = page.evaluate("window.location.href")
        login_indicators = ["login", "signin", "auth", "id.freenet.de"]
        if any(x in current_url.lower() for x in login_indicators):
            raise RuntimeError(
                f"SESSION_EXPIRED: Freenet Session abgelaufen — bitte neu einloggen. "
                f"URL: {current_url}"
            )
        try:
            login_form = page.locator("input#username, input[name='username'], input[type='password']")
            if login_form.count() > 0 and login_form.first.is_visible():
                raise RuntimeError(
                    "SESSION_EXPIRED: Freenet Login-Formular sichtbar — "
                    "bitte Session neu speichern über Admin UI → Download → Manueller Login."
                )
        except RuntimeError:
            raise
        except Exception:
            pass

        page.screenshot(path=f"{DOWNLOAD_DIR}/freenet-01-loaded.png")
        
        print("\n✅ Nutze gespeicherte Session...")
        time.sleep(2)
        page.screenshot(path=f"{DOWNLOAD_DIR}/freenet-02-loaded.png")
        
        # Suche Monats-Eintrag, hole Monatstext für Dateinamen
        print("\n📅 Suche Monatseintrag...")
        month_text = pick_month(page, month_offset=month_offset)
        if not month_text:
            page.screenshot(path=f"{DOWNLOAD_DIR}/freenet-error-no-month.png")
            raise RuntimeError("Konnte keinen Monatseintrag finden!")
        
        date_str = month_text_to_date_str(month_text)  # z.B. "2026-02"
        print(f"📅 Datums-String für Dateinamen: {date_str}")
        
        print("⏳ Warte 5 Sekunden auf Seite zu laden...")
        time.sleep(5)
        page.screenshot(path=f"{DOWNLOAD_DIR}/freenet-03-month-selected.png")
        
        # Download PDF
        print("\n📥 Suche PDF-Link...")
        with page.expect_download() as dl_info:
            if not click_top_pdf(page):
                page.screenshot(path=f"{DOWNLOAD_DIR}/freenet-error-no-pdf.png")
                raise RuntimeError("Konnte keinen PDF-Link finden!")
        
        download = dl_info.value
        out_file = save_download(download, DOWNLOAD_DIR, date_str)
        
        page.screenshot(path=f"{DOWNLOAD_DIR}/freenet-04-downloaded.png")
        
        context.close()
        
        return [out_file]


if __name__ == "__main__":
    import sys
    
    headless = True
    if len(sys.argv) > 1 and sys.argv[1] == "--gui":
        headless = False
    
    print("\n" + "="*60)
    if headless:
        print("🤖 HEADLESS-MODUS (automatisch, schnell)")
    else:
        print("🖥️  GUI-MODUS (du siehst den Browser)")
    print("="*60)
    
    run_freenet_download(headless=headless)
    
    print("\n" + "="*60)
    if headless:
        print("✅ Download abgeschlossen!")
    else:
        print("✅ GUI-Test abgeschlossen!")
    print("="*60)
