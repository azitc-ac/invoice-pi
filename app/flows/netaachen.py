import os
import re
import time
from playwright.sync_api import sync_playwright

DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/downloads")
PW_USERDATA = os.getenv("PW_USERDATA_NETAACHEN", "/pwdata/netaachen")
INVOICE_URL = "https://meinekundenwelt.netcologne.de/"

GER_MONTHS = [
    "Januar","Februar","März","April","Mai","Juni",
    "Juli","August","September","Oktober","November","Dezember"
]

MONTH_MAP = {
    "Januar": "01", "Februar": "02", "März": "03", "April": "04",
    "Mai": "05", "Juni": "06", "Juli": "07", "August": "08",
    "September": "09", "Oktober": "10", "November": "11", "Dezember": "12"
}

def month_text_to_date_str(month_text):
    """'Februar 2026' → '2026-02'"""
    try:
        parts = month_text.strip().split()
        month_num = MONTH_MAP.get(parts[0], "00")
        return f"{parts[1]}-{month_num}"
    except Exception:
        return "0000-00"

def click_top_pdf(page, date_str):
    """Klicke auf PDF-Link im Download-Dialog"""
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
        filename = f"Rechnung_NetAachen_{date_str}.pdf"
        path = os.path.join(DOWNLOAD_DIR, filename)
        download.save_as(path)
        print(f"✅ PDF gespeichert: {path}")
        return path
        
    except Exception as e:
        print(f"❌ Fehler: {e}")
        return None

def run_netaachen_download(headless=True, month_offset=0):
    """Download NetAachen mit gespeicherter Session"""
    
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
        import json as _json, os as _os
        storage_path = _os.path.join(PW_USERDATA, 'playwright-storage.json')
        if _os.path.isfile(storage_path):
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
        
        print(f"📖 Gehe zu {INVOICE_URL}")
        page.goto(INVOICE_URL, wait_until="domcontentloaded")
        
        time.sleep(3)
        page.screenshot(path=f"{DOWNLOAD_DIR}/netaachen-01-loaded.png")

        # Prüfen ob Session gültig ist (kein Login-Dialog)
        current_url = page.evaluate("window.location.href")
        login_indicators = ["login", "signin", "cas/login", "auth", "sso.netcologne"]
        if any(x in current_url.lower() for x in login_indicators):
            raise RuntimeError(
                f"SESSION_EXPIRED: NetAachen Session abgelaufen — bitte neu einloggen. "
                f"URL: {current_url}"
            )
        
        # Zusätzlich prüfen ob Login-Formular im DOM sichtbar
        try:
            login_form = page.locator("input[name='username'], input#username, input[type='password']")
            if login_form.count() > 0 and login_form.first.is_visible():
                raise RuntimeError(
                    "SESSION_EXPIRED: NetAachen Login-Formular sichtbar — "
                    "bitte Session neu speichern über Admin UI → Download → Manueller Login."
                )
        except RuntimeError:
            raise
        except Exception:
            pass

        print("✅ Nutze gespeicherte Session...")
        time.sleep(1)
        
        # Navigiere zu "Meine Rechnungen"
        print("\n📋 Navigiere zu Meine Rechnungen...")
        try:
            page.get_by_text("Meine Rechnungen").first.click()
            time.sleep(1)
        except:
            print("⚠️  Konnte nicht klicken")
        
        # Klicke auf Rechnung (aktuell oder Vormonat je nach month_offset)
        print(f"📄 Öffne Rechnung (offset={month_offset})...")
        date_str = "0000-00"
        try:
            if month_offset == 0:
                page.get_by_text("Aktuelle Rechnung").first.click()
            else:
                month_regex = "(" + "|".join(GER_MONTHS) + r")\s+20\d{2}"
                tiles = page.locator(f"text=/{month_regex}/i")
                count = tiles.count()
                print(f"🔍 Gefundene Monats-Tiles: {count}")
                if count >= month_offset:
                    tiles.nth(month_offset - 1).click()
                else:
                    print(f"⚠️  Vormonat nicht gefunden, nehme aktuell")
                    page.get_by_text("Aktuelle Rechnung").first.click()
            time.sleep(1)

            page_text = page.content()
            for monat in GER_MONTHS:
                monat_match = re.search(f"({monat} \\d{{4}})", page_text)
                if monat_match:
                    month_text = monat_match.group(1)
                    date_str = month_text_to_date_str(month_text)
                    print(f"✅ Rechnung: {month_text} → {date_str}")
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
        path = click_top_pdf(page, date_str)

        if path:
            page.screenshot(path=f"{DOWNLOAD_DIR}/netaachen-02-downloaded.png")
            context.close()
            return [path]
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
