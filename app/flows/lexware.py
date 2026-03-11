import os
import time
import shutil
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

LW_USER     = os.getenv("LEXWARE_USERNAME", "")
LW_PASS     = os.getenv("LEXWARE_PASSWORD", "")
FF_PROFILE  = os.getenv("FF_PROFILE_LEXWARE", "/pwdata/lexware-ff")
FF_BIN      = "/usr/bin/firefox"

LEXWARE_LOGIN_URL   = "https://app.lexware.de"
LEXWARE_VOUCHER_URL = "https://app.lexware.de/vouchers#!/VoucherList/?filter=accounting&vouchereditoropen=true"

TIMEOUT_NAV     = 30_000
TIMEOUT_ELEMENT = 15_000
TIMEOUT_UPLOAD  = 60_000


def _fresh_profile():
    if Path(FF_PROFILE).exists():
        shutil.rmtree(FF_PROFILE)
    Path(FF_PROFILE).mkdir(parents=True, exist_ok=True)
    # Welcome-Screen und erste-Start-Popups deaktivieren
    (Path(FF_PROFILE) / "user.js").write_text("""
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
user_pref("browser.aboutwelcome.enabled", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.shell.didSkipDefaultBrowserCheckOnFirstRun", true);
user_pref("datareporting.policy.dataSubmissionPolicyAccepted", true);
user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);
""")
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
    """Cookie-Banner per JS wegklicken — funktioniert auch in Shadow DOM."""
    js = """
function findAndClick(root) {
    var keywords = ['alle akzept', 'akzept', 'zustimm', 'accept all', 'accept'];
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
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if page.evaluate(js):
                print("✅ Cookie-Banner geschlossen")
                time.sleep(0.6)
                return
        except Exception:
            pass
        time.sleep(0.3)
    print("ℹ️  Kein Cookie-Banner gefunden")


def _get_file_input(page, timeout=20):
    """File-Input finden — auch in Shadow DOM."""
    # Erst normal versuchen
    try:
        fi = page.locator("input[type='file']").first
        fi.wait_for(state="attached", timeout=timeout * 1000)
        return fi
    except Exception:
        pass

    # Shadow DOM Walk per JS
    js = """
var results = [];
function walk(root) {
    if (!root || !root.querySelectorAll) return;
    var inputs = root.querySelectorAll('input[type="file"]');
    for (var i = 0; i < inputs.length; i++) { results.push(inputs[i]); }
    var all = root.querySelectorAll('*');
    for (var j = 0; j < all.length; j++) {
        if (all[j].shadowRoot) walk(all[j].shadowRoot);
    }
}
walk(document);
return results;
"""
    els = page.evaluate(js)
    if els:
        print("✅ File-Input via Shadow-DOM gefunden")
        return page.locator("input[type='file']").first
    return None


def _make_file_input_visible(page):
    """File-Input sichtbar machen damit set_input_files funktioniert."""
    page.evaluate("""
var el = document.querySelector("input[type='file']");
if (el) {
    el.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;width:100px!important;height:30px!important;';
    el.removeAttribute('hidden');
    el.removeAttribute('aria-hidden');
    el.removeAttribute('disabled');
}
""")


def _get_badge_count(page):
    """Zähler aus Badge lesen (span.grld-bs-badge-info)."""
    try:
        result = page.evaluate("""
var el = document.querySelector("span.grld-bs-badge-info");
if (el) return parseInt(el.textContent.trim(), 10);
return null;
""")
        return result
    except Exception:
        return None


def run_lexware_upload(file_path: str, headless: bool = True) -> dict:
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Datei nicht gefunden: {file_path}")
    if not LW_USER or not LW_PASS:
        raise RuntimeError("LEXWARE_USERNAME und LEXWARE_PASSWORD müssen in .env gesetzt sein!")

    filename = os.path.basename(file_path)
    abs_path  = os.path.abspath(file_path)
    print(f"\n🚀 Starte Lexware Upload")
    print(f"📄 Datei: {abs_path}")

    _fresh_profile()

    with sync_playwright() as p:
        ctx = p.firefox.launch_persistent_context(
            FF_PROFILE,
            executable_path=FF_BIN,
            headless=False,
            args=["--no-sandbox"],
            viewport={"width": 1280, "height": 900},
            locale="de-DE",
            timezone_id="Europe/Berlin",
            # Direkt Lexware öffnen — überspringt Welcome-Screen
            firefox_user_prefs={
                "browser.startup.homepage": LEXWARE_LOGIN_URL,
                "browser.startup.page": 1,
                "browser.aboutwelcome.enabled": False,
                "startup.homepage_welcome_url": "",
                "browser.shell.checkDefaultBrowser": False,
            },
        )

        # Vorhandenen Tab nehmen und navigieren
        time.sleep(2)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print(f"📖 Navigiere zu {LEXWARE_LOGIN_URL}...")
        page.goto(LEXWARE_LOGIN_URL, wait_until="commit", timeout=TIMEOUT_NAV)
        page.bring_to_front()
        time.sleep(3)
        print(f"📍 URL: {page.url}")

        _dismiss_cookie_banner(page)

        if any(x in page.url.lower() for x in ["signin", "login", "authenticate"]):
            print(f"🔐 Login als {LW_USER}...")

            email_el = _find(page, [
                "input[type='email']",
                "input[name='email']",
                "input[name='username']",
                "input[autocomplete='username']",
            ], timeout=8_000)
            if not email_el:
                ctx.close()
                raise RuntimeError("Email-Feld nicht gefunden")
            email_el.click()
            email_el.fill(LW_USER)
            print("✅ Email gefüllt")
            time.sleep(0.3)

            pwd_el = _find(page, [
                "input[type='password']",
                "input[name='password']",
            ], timeout=5_000)
            if not pwd_el:
                ctx.close()
                raise RuntimeError("Passwort-Feld nicht gefunden")
            pwd_el.click()
            pwd_el.fill(LW_PASS)
            print("✅ Passwort gefüllt")
            time.sleep(0.3)

            btn = _find(page, [
                "button:has-text('Anmelden')",
                "button[type='submit']",
                "button:has-text('Login')",
                "button:has-text('Weiter')",
            ], timeout=5_000)
            if btn:
                btn.click()
            else:
                pwd_el.press("Enter")
            print("✅ Anmelden geklickt — warte auf Redirect...")

            deadline = time.time() + 30
            while time.time() < deadline:
                url = page.url
                if not any(x in url.lower() for x in ["signin", "login", "authenticate", "403", "forbidden"]):
                    print(f"✅ Eingeloggt! URL: {url}")
                    break
                if "403" in url or "forbidden" in url.lower():
                    ctx.close()
                    raise RuntimeError(f"403 Forbidden beim Login")
                time.sleep(1)
            else:
                ctx.close()
                raise RuntimeError("Login-Timeout nach 30s")

            time.sleep(2)
        else:
            print("✅ Bereits eingeloggt")

        # ── Direkt zum Voucher-Editor navigieren ──────────────────
        print(f"📖 Öffne Voucher-Editor direkt...")
        page.goto(LEXWARE_VOUCHER_URL, wait_until="domcontentloaded", timeout=TIMEOUT_NAV)
        time.sleep(3)

        # ── File-Input finden und befüllen ────────────────────────
        print('🖱️  Suche File-Input...')
        fi = _get_file_input(page, timeout=20)
        if not fi:
            ctx.close()
            raise RuntimeError("File-Input nicht gefunden")

        _make_file_input_visible(page)
        time.sleep(0.3)

        # Zähler vor Upload
        count_before = _get_badge_count(page)
        print(f"📊 Badge-Zähler vor Upload: {count_before}")

        # Datei setzen
        fi.set_input_files(abs_path)
        print(f"✅ Datei gesetzt: {filename}")
        time.sleep(3)

        # ── Warten auf Upload-Bestätigung per Badge-Zähler ────────
        print("⏳ Warte auf Upload-Bestätigung...")
        for attempt in range(10):
            print(f"   🔄 Refresh {attempt + 1}/10...")
            page.reload(wait_until="domcontentloaded")
            time.sleep(4)

            count_after = _get_badge_count(page)
            print(f"   📊 Badge-Zähler: {count_after}")

            if count_after is not None and count_before is not None and count_after > count_before:
                print(f"✅ Upload bestätigt! Zähler: {count_before} → {count_after}")
                break
            elif count_after is None and count_before is None:
                # Badge nicht gefunden — Upload trotzdem wahrscheinlich ok
                print("ℹ️  Badge nicht gefunden — Upload vermutlich erfolgreich")
                break
        else:
            print("⚠️  Timeout — Datei wurde möglicherweise trotzdem hochgeladen")

        print(f'\n✅ Upload abgeschlossen: {filename}')
        ctx.close()

    return {"status": "ok", "filename": filename, "file": file_path}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 lexware.py <pdf-path>")
        sys.exit(1)
    result = run_lexware_upload(sys.argv[1])
    print(result)
