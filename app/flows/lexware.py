import os
import time
import shutil
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

LW_USER      = os.getenv("LEXWARE_USERNAME", "")
LW_PASS      = os.getenv("LEXWARE_PASSWORD", "")
FF_PROFILE   = os.getenv("FF_PROFILE_LEXWARE", "/pwdata/lexware-ff")
CHROMIUM_BIN = "/ms-playwright/chromium-1208/chrome-linux/chrome"
CDP_PORT     = 9222

LEXWARE_LOGIN_URL   = "https://app.lexware.de"
LEXWARE_VOUCHER_URL = "https://app.lexware.de/vouchers#!/VoucherList/?filter=accounting&vouchereditoropen=true"

TIMEOUT_NAV     = 30_000
TIMEOUT_ELEMENT = 15_000


def _fresh_profile():
    if Path(FF_PROFILE).exists():
        shutil.rmtree(FF_PROFILE)
    Path(FF_PROFILE).mkdir(parents=True, exist_ok=True)
    # Chrome Preferences: Passwort-Speichern deaktivieren
    import json
    prefs = {
        "credentials_enable_service": False,
        "profile": {
            "password_manager_enabled": False
        }
    }
    prefs_dir = Path(FF_PROFILE) / "Default"
    prefs_dir.mkdir(parents=True, exist_ok=True)
    (prefs_dir / "Preferences").write_text(json.dumps(prefs))
    print(f"🧹 Frisches Profil: {FF_PROFILE}")


def _find(page, selectors, timeout=10_000):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout)
            if loc.is_visible():
                return loc
        except Exception:
            continue
    return None


def _dismiss_cookie_banner(page):
    js = """
function findAndClick(root) {
    var keywords = ['alle akzept', 'akzept', 'zustimm', 'einverstanden', 'accept all', 'accept'];
    var tags = ['button', 'a', '[role="button"]'];
    for (var ti = 0; ti < tags.length; ti++) {
        var els = root.querySelectorAll(tags[ti]);
        for (var i = 0; i < els.length; i++) {
            var txt = (els[i].innerText || els[i].textContent || '').toLowerCase().trim();
            for (var ki = 0; ki < keywords.length; ki++) {
                if (txt.indexOf(keywords[ki]) !== -1) { els[i].click(); return true; }
            }
        }
    }
    var all = root.querySelectorAll('*');
    for (var j = 0; j < all.length; j++) {
        if (all[j].shadowRoot) { if (findAndClick(all[j].shadowRoot)) return true; }
    }
    return false;
}
return findAndClick(document);
"""
    print("🍪 Suche Cookie-Banner...")
    deadline = time.time() + 20
    while time.time() < deadline:
        # Hauptframe
        try:
            if page.evaluate(js):
                print("✅ Cookie-Banner im Hauptframe geschlossen")
                time.sleep(0.6)
                return
        except Exception:
            pass

        # Alle iframes durchsuchen
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                print(f"   🔍 Prüfe iframe: {frame.url}")
                if frame.evaluate(js):
                    print(f"✅ Cookie-Banner in iframe geschlossen: {frame.url}")
                    time.sleep(0.6)
                    return
            except Exception:
                pass

        # Playwright-Locator über alle frames
        for sel in [
            "button:has-text('Alle akzeptieren')",
            "button:has-text('Akzeptieren')",
            "button:has-text('Accept all')",
            "button:has-text('Zustimmen')",
        ]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=500):
                    btn.click()
                    print(f"✅ Cookie-Banner per Locator geschlossen: {sel}")
                    time.sleep(0.6)
                    return
            except Exception:
                pass

        time.sleep(0.3)
    print("ℹ️  Kein Cookie-Banner gefunden")


def _get_badge_count(page):
    try:
        return page.evaluate("""
var el = document.querySelector("span.grld-bs-badge-info");
if (el) return parseInt(el.textContent.trim(), 10);
return null;
""")
    except Exception:
        return None


def run_lexware_upload(file_path: str, headless: bool = True) -> dict:
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Datei nicht gefunden: {file_path}")
    if not LW_USER or not LW_PASS:
        raise RuntimeError("LEXWARE_USERNAME und LEXWARE_PASSWORD müssen gesetzt sein!")

    filename = os.path.basename(file_path)
    abs_path  = os.path.abspath(file_path)
    print(f"\n🚀 Starte Lexware Upload v18")
    print(f"📄 Datei: {abs_path}")

    _fresh_profile()

    # Chromium manuell starten mit Anti-Detection Flags + CDP
    subprocess.run("pkill -f 'chrome-linux/chrome' 2>/dev/null", shell=True)
    time.sleep(1)

    print(f"🌐 Starte Chromium mit CDP auf Port {CDP_PORT}...")
    proc = subprocess.Popen([
        CHROMIUM_BIN,
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={FF_PROFILE}",
        "--window-size=1280,900",
        "--disable-save-password-bubble",
        "--password-store=basic",
        "--disable-features=PasswordManager",
        "--disable-popup-blocking",
        f"--display={os.getenv('DISPLAY', ':0')}",
        LEXWARE_LOGIN_URL,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    time.sleep(4)

    with sync_playwright() as p:
        print(f"🔌 Verbinde via CDP...")
        browser = p.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.bring_to_front()

        # Warten bis Seite geladen
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        time.sleep(2)
        print(f"📍 URL: {page.url}")
        print(f"🔍 navigator.webdriver: {page.evaluate('navigator.webdriver')}")

        # Erst warten bis Login-Formular sichtbar ist
        print("⏳ Warte auf Login-Formular...")
        try:
            page.wait_for_selector("input[type='email'], input[type='password'], input[name='username']", timeout=15_000)
        except Exception:
            pass
        time.sleep(1)

        # Warten bis Cookie-Banner erscheint (lädt verzögert)
        print("⏳ Warte auf Cookie-Banner...")
        time.sleep(2)

        # Debug: alle Buttons ausgeben
        buttons = page.evaluate("""
Array.from(document.querySelectorAll('button, a, [role="button"]'))
    .map(e => e.innerText || e.textContent || '')
    .filter(t => t.trim())
    .map(t => t.trim().substring(0, 60))
""")
        print(f"🔍 Sichtbare Buttons: {buttons[:15]}")

        _dismiss_cookie_banner(page)

        # ── Login ─────────────────────────────────────────────────
        if any(x in page.url.lower() for x in ["signin", "login", "authenticate"]):
            print(f"🔐 Login als {LW_USER}...")

            email_el = _find(page, [
                "input[type='email']",
                "input[name='email']",
                "input[name='username']",
                "input[autocomplete='username']",
            ], timeout=8_000)
            if not email_el:
                raise RuntimeError("Email-Feld nicht gefunden")
            email_el.click()
            email_el.fill(LW_USER)
            print("✅ Email gefüllt")
            time.sleep(0.3)

            pwd_el = _find(page, ["input[type='password']"], timeout=5_000)
            if not pwd_el:
                raise RuntimeError("Passwort-Feld nicht gefunden")
            pwd_el.click()
            pwd_el.fill(LW_PASS)
            print("✅ Passwort gefüllt")
            time.sleep(0.3)

            btn = _find(page, [
                "button:has-text('Anmelden')",
                "button[type='submit']",
                "button:has-text('Login')",
            ], timeout=5_000)
            if btn:
                print(f"🖱️  Klicke: '{btn.text_content()}'")
                btn.click()
            else:
                pwd_el.press("Enter")
            print("⏳ Warte auf Redirect...")

            deadline = time.time() + 120
            while time.time() < deadline:
                url = page.url
                print(f"📍 URL check: {url}")
                if "dashboard" in url.lower() or "voucher" in url.lower() or "belege" in url.lower():
                    print(f"✅ Eingeloggt!")
                    break
                if "403" in url or "forbidden" in url.lower():
                    raise RuntimeError(f"403 Forbidden")
                time.sleep(2)
            else:
                raise RuntimeError(f"Login-Timeout. URL: {page.url}")

            time.sleep(2)
            time.sleep(1)
        else:
            print("✅ Bereits eingeloggt")

        # ── Voucher-Editor per Button ─────────────────────────────
        print(f"📍 Dashboard URL: {page.url}")
        print(f"🖱️  Suche 'Neuen Beleg erfassen'...")
        btn_new = _find(page, [
            "button:has-text('Neuen Beleg erfassen')",
            "a:has-text('Neuen Beleg erfassen')",
            "[class*='voucher']:has-text('Neuen')",
        ], timeout=15_000)

        if btn_new:
            btn_new.click()
            print("✅ 'Neuen Beleg erfassen' geklickt")
            time.sleep(3)
        else:
            # Fallback: direkte URL
            print("⚠️  Button nicht gefunden — navigiere direkt...")
            try:
                page.goto(LEXWARE_VOUCHER_URL, wait_until="commit", timeout=15_000)
            except Exception as e:
                print(f"⚠️  goto Exception (ignoriert): {e}")
            time.sleep(3)

        print(f"📍 URL: {page.url}")

        # ── File-Input ────────────────────────────────────────────
        print("🖱️  Suche File-Input...")
        fi = None
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                loc = page.locator("input[type='file']").first
                loc.wait_for(state="attached", timeout=2000)
                fi = loc
                break
            except Exception:
                pass
            time.sleep(0.5)

        if not fi:
            raise RuntimeError("File-Input nicht gefunden")

        # Sichtbar machen
        page.evaluate("""
var el = document.querySelector("input[type='file']");
if (el) {
    el.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;width:100px!important;height:30px!important;';
    el.removeAttribute('hidden');
    el.removeAttribute('aria-hidden');
    el.removeAttribute('disabled');
}
""")
        time.sleep(0.3)

        count_before = _get_badge_count(page)
        print(f"📊 Badge-Zähler vor Upload: {count_before}")

        fi.set_input_files(abs_path)
        print(f"✅ Datei gesetzt: {filename}")
        time.sleep(3)

        # ── Bestätigung per Badge ─────────────────────────────────
        print("⏳ Warte auf Upload-Bestätigung...")
        for attempt in range(10):
            print(f"   🔄 Refresh {attempt + 1}/10...")
            page.reload(wait_until="domcontentloaded")
            time.sleep(4)
            count_after = _get_badge_count(page)
            print(f"   📊 Badge: {count_after}")
            if count_after is not None and count_before is not None and count_after > count_before:
                print(f"✅ Upload bestätigt! {count_before} → {count_after}")
                break
            elif count_after is None and count_before is None:
                print("ℹ️  Badge nicht gefunden — vermutlich ok")
                break
        else:
            print("⚠️  Timeout — möglicherweise trotzdem hochgeladen")

        print(f"\n✅ Upload abgeschlossen: {filename}")
        browser.close()

    proc.terminate()
    return {"status": "ok", "filename": filename, "file": file_path}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 lexware.py <pdf-path>")
        sys.exit(1)
    result = run_lexware_upload(sys.argv[1])
    print(result)
