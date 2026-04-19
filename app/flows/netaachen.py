import os
import re
import time
from playwright.sync_api import sync_playwright

NA_USER      = os.getenv("NETAACHEN_USERNAME")
NA_PASS      = os.getenv("NETAACHEN_PASSWORD")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/downloads")
PW_USERDATA  = os.getenv("PW_USERDATA_NETAACHEN", "/pwdata/netaachen")

LOGIN_URL = (
    "https://sso.netcologne.de/cas/login"
    "?service=https://meinekundenwelt.netcologne.de/&mandant=na"
)

GER_MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]

MONTH_MAP = {
    "Januar": "01", "Februar": "02", "März": "03", "April": "04",
    "Mai": "05", "Juni": "06", "Juli": "07", "August": "08",
    "September": "09", "Oktober": "10", "November": "11", "Dezember": "12",
}


def _dismiss_cookie_banner(page):
    selectors = [
        # NetAachen / NetCologne: Accept-Link ist ein <a>-Tag, kein <button>
        "#nc-cookiebanner a:has-text('Alle akzeptieren')",
        "[name='nc-cookiebanner'] a:has-text('Alle akzeptieren')",
        "a:has-text('Alle akzeptieren')",
        "#nc-cookiebanner a",
        "[name='nc-cookiebanner'] a",
        # Fallback mit button-Tags
        "#nc-cookiebanner button",
        "[name='nc-cookiebanner'] button",
        "button:has-text('Alle akzeptieren')",
        "button:has-text('Akzeptieren')",
        "a:has-text('Akzeptieren')",
        "button:has-text('Zustimmen')",
        "button:has-text('Einverstanden')",
        # OneTrust
        "button#onetrust-accept-btn-handler",
        "button.onetrust-accept-btn-handler",
        "button:has-text('Accept all')",
        "button:has-text('Accept')",
        "[id*='accept'][id*='cookie']",
        "[class*='accept'][class*='cookie']",
    ]
    deadline = time.time() + 10
    while time.time() < deadline:
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=500):
                    btn.click()
                    print(f"🍪 Cookie-Banner weggeklickt ({sel})")
                    time.sleep(1)
                    return
            except Exception:
                continue
        time.sleep(0.5)
    # Letzter Versuch per JavaScript
    try:
        clicked = page.evaluate("""
            () => {
                const banner = document.querySelector('#nc-cookiebanner, [name="nc-cookiebanner"]');
                if (!banner) return false;
                const elems = banner.querySelectorAll('a, button');
                const accept = [...elems].find(b => b.textContent.includes('akzeptieren') || b.textContent.includes('Akzeptieren') || b.textContent.includes('Accept'));
                if (accept) { accept.click(); return true; }
                if (elems.length) { elems[elems.length - 1].click(); return true; }
                return false;
            }
        """)
        if clicked:
            print("🍪 Cookie-Banner per JS weggeklickt")
            time.sleep(1)
            return
    except Exception:
        pass
    print("ℹ️ Kein Cookie-Banner gefunden")


def _login(page):
    """Füllt NetAachen Login-Formular aus und wartet auf Redirect."""
    print("🔐 Fülle Login-Formular aus...")
    try:
        page.wait_for_selector("input#username, input[name='username']", timeout=10000)
        page.fill("input#username", NA_USER or "")
        page.fill("input#password", NA_PASS or "")
        print("✅ Credentials ausgefüllt")
    except Exception as e:
        raise RuntimeError(f"Login-Formular nicht gefunden: {e}")

    try:
        page.click("button[type='submit'], input[type='submit']", timeout=5000)
    except Exception as e:
        print(f"⚠️ Submit-Button: {e}")

    print("⏳ Warte auf Login-Redirect...")
    try:
        page.wait_for_function(
            "() => window.location.href.includes('meinekundenwelt') "
            "   && !window.location.href.includes('cas/login')",
            timeout=30000,
        )
        print(f"✅ Login erfolgreich: {page.url}")
    except Exception as e:
        raise RuntimeError(f"Login fehlgeschlagen oder Timeout: {e}")
    time.sleep(2)


def month_text_to_date_str(month_text):
    try:
        parts = month_text.strip().split()
        return f"{parts[1]}-{MONTH_MAP.get(parts[0], '00')}"
    except Exception:
        return "0000-00"


def click_top_pdf(page, date_str):
    print("📥 Suche PDF-Link im Dialog...")
    try:
        page.locator("div[data-e2e='modal-billing-download-landline']").wait_for(timeout=5000)
        print("✅ Download-Dialog gefunden")
        pdf_link = page.locator(
            "div[data-e2e='modal-billing-download-landline'] >> text=PDF"
        ).first
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
        print(f"❌ PDF-Download Fehler: {e}")
        return None


def run_netaachen_download(headless=True, month_offset=0):
    """NetAachen Download mit frischem Login.

    Kein CDP nötig — NetAachen hat kein Cloudflare.
    """
    print(f"\n🚀 Starte NetAachen Download (fresh login, offset={month_offset})")

    for lock_file in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        lock_path = os.path.join(PW_USERDATA, lock_file)
        if os.path.lexists(lock_path):
            os.remove(lock_path)
            print(f"🧹 Lock entfernt: {lock_path}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PW_USERDATA,
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-setuid-sandbox",
            ],
        )
        page = context.new_page()

        print(f"📖 Navigiere zu {LOGIN_URL}")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_url(
                lambda url: "meinekundenwelt" in url or "sso.netcologne" in url or "cas/login" in url,
                timeout=10000,
            )
        except Exception:
            pass

        current_url = page.url
        print(f"📍 URL nach Navigation: {current_url}")

        if "meinekundenwelt" in current_url and "cas/login" not in current_url:
            print("✅ Bereits eingeloggt (Session noch aktiv)")
        else:
            _login(page)

        # Kurz warten damit der Cookie-Banner per JS laden kann
        page.wait_for_load_state("load")
        time.sleep(2)
        _dismiss_cookie_banner(page)

        page.screenshot(path=f"{DOWNLOAD_DIR}/netaachen-01-logged-in.png")

        # Navigiere zu "Meine Rechnungen"
        print("\n📋 Öffne Meine Rechnungen...")
        try:
            page.get_by_text("Meine Rechnungen").first.click(timeout=5000)
            time.sleep(2)
        except Exception:
            # Cookie-Banner könnte erst jetzt erschienen sein
            _dismiss_cookie_banner(page)
            try:
                page.get_by_text("Meine Rechnungen").first.click(timeout=10000)
                time.sleep(2)
            except Exception as e:
                print(f"⚠️ Meine Rechnungen: {e}")

        # Rechnung auswählen
        print(f"📄 Wähle Rechnung (offset={month_offset})...")
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
                    print("⚠️ Vormonat nicht gefunden, nehme Aktuelle Rechnung")
                    page.get_by_text("Aktuelle Rechnung").first.click()
            time.sleep(1)

            page_text = page.content()
            for monat in GER_MONTHS:
                m = re.search(f"({monat} \\d{{4}})", page_text)
                if m:
                    date_str = month_text_to_date_str(m.group(1))
                    print(f"✅ Datum: {m.group(1)} → {date_str}")
                    break
        except Exception as e:
            print(f"⚠️ Rechnungsauswahl: {e}")

        # Download klicken
        print("📥 Klicke Download...")
        try:
            page.get_by_text("Download").first.click()
            time.sleep(1)
        except Exception as e:
            print(f"⚠️ Download-Button: {e}")

        path = click_top_pdf(page, date_str)

        if path:
            page.screenshot(path=f"{DOWNLOAD_DIR}/netaachen-02-done.png")
            context.close()
            return [path]
        else:
            page.screenshot(path=f"{DOWNLOAD_DIR}/netaachen-error.png")
            context.close()
            raise RuntimeError("PDF-Download fehlgeschlagen!")


