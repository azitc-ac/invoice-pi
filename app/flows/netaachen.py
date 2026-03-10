import os
import time
from playwright.sync_api import sync_playwright

DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/downloads")
PW_USERDATA = os.getenv("PW_USERDATA_NETAACHEN", "/pwdata/netaachen")
INVOICE_URL = "https://meinekundenwelt.netcologne.de/"

def click_top_pdf(page):
    """Klicke auf PDF-Link im Download-Dialog, gibt Dateipfad zurück"""
    import time
    
    print(f"📥 Suche PDF-Link...")
    
    try:
        # Warte auf Dialog
        page.locator("div[data-e2e='modal-billing-download-landline']").wait_for(timeout=5000)
        print("✅ Download-Dialog gefunden")
        
        # Klicke auf PDF
        pdf_link = page.locator("div[data-e2e='modal-billing-download-landline'] >> text=PDF").first
        pdf_link.scroll_into_view_if_needed()
        time.sleep(1)
        
        with page.expect_download() as dl_info:
            pdf_link.click()
        
        download = dl_info.value
        path = os.path.join(DOWNLOAD_DIR, download.suggested_filename)
        download.save_as(path)
        print(f"✅ PDF gespeichert: {path}")
        return path  # Dateipfad zurückgeben statt True
        
    except Exception as e:
        print(f"❌ Fehler: {e}")
        return None

def run_netaachen_download(headless=True):
    """Download NetAachen mit gespeicherter Session"""
    
    print(f"\n🚀 Starte Playwright (headless={headless})")
    print(f"📁 User Data Dir: {PW_USERDATA}")
    
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
        
        page = context.new_page()
        
        print(f"📖 Gehe zu {INVOICE_URL}")
        page.goto(INVOICE_URL, wait_until="domcontentloaded")
        
        time.sleep(1)
        page.screenshot(path=f"{DOWNLOAD_DIR}/netaachen-01-loaded.png")
        
        print("✅ Nutze gespeicherte Session...")
        time.sleep(1)
        
        # Navigiere zu "Meine Rechnungen"
        print("\n📋 Navigiere zu Meine Rechnungen...")
        try:
            page.get_by_text("Meine Rechnungen").first.click()
            time.sleep(1)
        except:
            print("⚠️  Konnte nicht klicken")
        
        # Klicke auf "Aktuelle Rechnung"
        print("📄 Öffne aktuelle Rechnung...")
        try:
            page.get_by_text("Aktuelle Rechnung").first.click()
            time.sleep(1)
            
            import re
            page_text = page.content()
            monate = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
            
            for monat in monate:
                monat_match = re.search(f"{monat} \\d{{4}}", page_text)
                if monat_match:
                    print(f"✅ Öffne aktuelle Rechnung: {monat_match.group()}")
                    break
            
        except Exception as e:
            print(f"⚠️  Button nicht gefunden: {e}")
        
        # Klicke auf "Download"
        print("📥 Klicke Download...")
        try:
            page.get_by_text("Download").first.click()
            time.sleep(1)
        except:
            print("⚠️  Download-Button nicht gefunden")
        
        # Suche PDF-Link und lade herunter
        print("\n📥 Suche PDF-Link im Dialog...")
        path = click_top_pdf(page)

        if path:
            page.screenshot(path=f"{DOWNLOAD_DIR}/netaachen-02-downloaded.png")
            context.close()
            return [path]  # Liste zurückgeben, konsistent mit freenet.py
        else:
            print("❌ Konnte PDF nicht finden!")
            page.screenshot(path=f"{DOWNLOAD_DIR}/netaachen-error.png")
            context.close()
            raise RuntimeError("PDF-Download fehlgeschlagen!")


if __name__ == "__main__":
    import sys
    
    headless = True
    if len(sys.argv) > 1 and sys.argv[1] == "--gui":
        headless = False
    
    print("\n" + "="*60)
    if headless:
        print("🤖 HEADLESS-MODUS")
    else:
        print("🖥️  GUI-MODUS")
    print("="*60)
    
    run_netaachen_download(headless=headless)
    
    print("\n" + "="*60)
    print("✅ Download abgeschlossen!")
    print("="*60)
