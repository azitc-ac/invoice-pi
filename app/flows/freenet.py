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

def pick_latest_month(page):
    """Suche nach NEUESTEN Monatseintrag"""
    month_regex = "(" + "|".join(GER_MONTHS) + r")\s+20\d{2}"
    tiles = page.locator(f"text=/{month_regex}/i")
    
    print(f"🔍 Suche Monate: {tiles.count()} gefunden")
    
    if tiles.count() > 0:
        # Hole den Text des Monats
        month_text = tiles.first.text_content()
        tiles.first.click()
        print(f"✅ Klicke auf neuesten Monat: {month_text}")
        return True
    
    print("❌ Keine Monate gefunden!")
    return False

def click_top_pdf(page):
    """Klicke auf obersten PDF-Link (nach Y-Position sortiert, wie im Selenium-Code)"""
    import time
    
    print(f"🔍 Suche PDF-Links...")
    
    # Hole alle PDF-Links auf der Seite
    pdflinks = page.get_by_text("PDF")
    count = pdflinks.count()
    print(f"📝 Gefunden: {count} PDF-Links")
    
    if count == 0:
        print("❌ Keine PDF-Links gefunden!")
        return False
    
    # Sammle alle Links mit ihren Y-Positionen
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
    
    # Sortiere nach Y-Position (oben = kleinste Y)
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

def save_download(download, download_dir):
    """Speichere Download"""
    path = os.path.join(download_dir, download.suggested_filename)
    download.save_as(path)
    print(f"✅ PDF gespeichert: {path}")
    return path

def run_freenet_download(headless=True):
    """
    Download Freenet Rechnungen via Playwright
    
    headless=False: Manuelles Einloggen + Session speichern (einmalig!)
    headless=True: Nutzt gespeicherte Session (automatisch)
    """
    
    print(f"\n🚀 Starte Playwright (headless={headless})")
    print(f"📁 User Data Dir: {PW_USERDATA}")
    
    with sync_playwright() as p:
        # Nutze persistent_context für Session-Speicherung
        context = p.chromium.launch_persistent_context(
            user_data_dir=PW_USERDATA,  # ← Session wird hier gespeichert!
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",  # ← gegen Bot-Detection
                "--disable-setuid-sandbox",
            ]
        )
        
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
        page.screenshot(path=f"{DOWNLOAD_DIR}/freenet-01-loaded.png")
        
        # Nutze gespeicherte Session
        print("\n✅ Nutze gespeicherte Session...")
        time.sleep(2)
        page.screenshot(path=f"{DOWNLOAD_DIR}/freenet-02-loaded.png")
        
        # Suche Monats-Eintrag
        print("\n📅 Suche Monatseintrag...")
        if not pick_latest_month(page):
            page.screenshot(path=f"{DOWNLOAD_DIR}/freenet-error-no-month.png")
            raise RuntimeError("Konnte keinen Monatseintrag finden!")
        
        # Lange warten auf Seite zu laden/expandieren
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
        out_file = save_download(download, DOWNLOAD_DIR)
        
        page.screenshot(path=f"{DOWNLOAD_DIR}/freenet-04-downloaded.png")
        
        context.close()
        
        return [out_file]


if __name__ == "__main__":
    import sys
    
    # Checke Kommandozeilen-Argument
    headless = True  # Default: Headless-Modus
    
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
