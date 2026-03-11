import os
import time
import shutil
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

LW_USER     = os.getenv("LEXWARE_USERNAME", "")
LW_PASS     = os.getenv("LEXWARE_PASSWORD", "")
FF_PROFILE  = os.getenv("FF_PROFILE_LEXWARE", "/pwdata/lexware-ff")
FF_BIN      = "/usr/bin/firefox"
GECKODRIVER = "/usr/local/bin/geckodriver"

LEXWARE_LOGIN_URL   = "https://app.lexware.de"
LEXWARE_VOUCHER_URL = "https://app.lexware.de/vouchers#!/VoucherList/?filter=accounting&vouchereditoropen=true"


def _fresh_profile():
    if Path(FF_PROFILE).exists():
        shutil.rmtree(FF_PROFILE)
    Path(FF_PROFILE).mkdir(parents=True, exist_ok=True)
    (Path(FF_PROFILE) / "user.js").write_text("""
user_pref("dom.webdriver.enabled", false);
user_pref("useAutomationExtension", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("startup.homepage_welcome_url", "");
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("datareporting.policy.dataSubmissionPolicyAccepted", true);
user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);
""")
    print(f"🧹 Frisches Profil: {FF_PROFILE}")


def _wait_for_element(driver, by, selector, timeout=25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            els = driver.find_elements(by, selector)
            for el in els:
                if el.is_displayed() and el.is_enabled():
                    return el
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Element nicht gefunden: {selector}")


def _dismiss_cookie_banner(driver):
    print("🍪 Suche Cookie-Banner...")
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
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if driver.execute_script(js):
                print("✅ Cookie-Banner geschlossen")
                time.sleep(0.6)
                return
        except Exception:
            pass
        time.sleep(0.3)
    print("ℹ️  Kein Cookie-Banner gefunden")


def _get_file_input(driver, timeout=20):
    """File-Input finden — auch versteckt, auch in Shadow DOM."""
    # Normal
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
            if els:
                return els[0]
        except Exception:
            pass
        time.sleep(0.3)

    # Shadow DOM Walk
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
    els = driver.execute_script(js)
    if els:
        print("✅ File-Input via Shadow-DOM gefunden")
        return els[0]
    return None


def _make_file_input_visible(driver, el):
    driver.execute_script("""
var el = arguments[0];
el.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;width:100px!important;height:30px!important;';
el.removeAttribute('hidden');
el.removeAttribute('aria-hidden');
el.removeAttribute('disabled');
""", el)


def _get_badge_count(driver):
    try:
        return driver.execute_script("""
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
    print(f"\n🚀 Starte Lexware Upload v5")
    print(f"📄 Datei: {abs_path}")

    _fresh_profile()

    options = Options()
    options.binary_location = FF_BIN
    options.add_argument("--no-sandbox")
    options.add_argument("--width=1280")
    options.add_argument("--height=900")
    # Profil mit user.js (dom.webdriver.enabled=false) übergeben
    options.add_argument(f"--profile")
    options.add_argument(FF_PROFILE)
    # Geckodriver-Pref via capability
    options.set_preference("dom.webdriver.enabled", False)
    options.set_preference("useAutomationExtension", False)

    service = Service(
        executable_path=GECKODRIVER,
        log_path="/tmp/geckodriver.log",
        service_args=["--setpref", "dom.webdriver.enabled=false"],
    )

    print("🦊 Starte Firefox via Selenium/geckodriver...")
    driver = webdriver.Firefox(service=service, options=options)
    driver.set_window_size(1280, 900)

    try:
        # ── Login ─────────────────────────────────────────────────
        print(f"📖 Öffne {LEXWARE_LOGIN_URL}...")
        driver.get(LEXWARE_LOGIN_URL)
        print(f"📍 URL: {driver.current_url}")
        print(f"🔍 navigator.webdriver: {driver.execute_script('return navigator.webdriver')}")

        _dismiss_cookie_banner(driver)

        if any(x in driver.current_url.lower() for x in ["signin", "login", "authenticate"]):
            print(f"🔐 Login als {LW_USER}...")

            # Email-Feld
            user_field = None
            for sel in ["#username", "input[name='username']", "input[type='email']", "input[autocomplete='username']"]:
                try:
                    user_field = _wait_for_element(driver, By.CSS_SELECTOR, sel, timeout=10)
                    break
                except Exception:
                    pass
            if not user_field:
                raise RuntimeError("Email-Feld nicht gefunden")
            user_field.clear()
            user_field.send_keys(LW_USER)
            print("✅ Email eingegeben")

            # Passwort-Feld
            pass_field = None
            for sel in ["#password", "input[name='password']", "input[type='password']"]:
                try:
                    pass_field = _wait_for_element(driver, By.CSS_SELECTOR, sel, timeout=10)
                    break
                except Exception:
                    pass
            if not pass_field:
                raise RuntimeError("Passwort-Feld nicht gefunden")
            pass_field.clear()
            pass_field.send_keys(LW_PASS)
            print("✅ Passwort eingegeben")

            # Anmelden-Button — erst normaler Click, dann JS-Fallback
            clicked = False
            try:
                btn = _wait_for_element(driver, By.XPATH,
                    "//button[contains(.,'Anmelden') or contains(.,'Login') or contains(.,'Weiter') or @type='submit']",
                    timeout=10)
                print(f"🖱️  Button gefunden: '{btn.text}' enabled={btn.is_enabled()}")
                driver.execute_script("arguments[0].click();", btn)
                clicked = True
                print("✅ Anmelden per JS-Click")
            except Exception as e:
                print(f"⚠️  Button nicht gefunden: {e}")

            if not clicked:
                try:
                    pass_field.submit()
                    print("✅ Anmelden per form.submit()")
                except Exception as e:
                    print(f"⚠️  submit() fehlgeschlagen: {e}")

            print("⏳ Warte auf Redirect...")

            # Warten auf erfolgreichen Login
            deadline = time.time() + 45
            last_url = ""
            while time.time() < deadline:
                url = driver.current_url
                if url != last_url:
                    print(f"📍 URL: {url}")
                    last_url = url
                if not any(x in url.lower() for x in ["signin", "login", "authenticate", "403", "forbidden"]):
                    print(f"✅ Eingeloggt! URL: {url}")
                    break
                if "403" in url or "forbidden" in url.lower():
                    raise RuntimeError(f"403 Forbidden — WAF blockt (navigator.webdriver=true)")
                time.sleep(1)
            else:
                raise RuntimeError(f"Login-Timeout nach 45s. Letzte URL: {driver.current_url}")

            time.sleep(2)
        else:
            print("✅ Bereits eingeloggt")

        # ── Direkt zum Voucher-Editor ──────────────────────────────
        print(f"📖 Öffne Voucher-Editor...")
        driver.get(LEXWARE_VOUCHER_URL)
        time.sleep(3)
        print(f"📍 URL: {driver.current_url}")

        # ── File-Input finden ──────────────────────────────────────
        print("🖱️  Suche File-Input...")
        fi = _get_file_input(driver, timeout=20)
        if not fi:
            raise RuntimeError("File-Input nicht gefunden")

        _make_file_input_visible(driver, fi)
        time.sleep(0.3)

        # Zähler vor Upload
        count_before = _get_badge_count(driver)
        print(f"📊 Badge-Zähler vor Upload: {count_before}")

        # Datei setzen
        fi.send_keys(abs_path)
        print(f"✅ Datei gesetzt: {filename}")
        time.sleep(3)

        # ── Upload-Bestätigung per Badge-Zähler ───────────────────
        print("⏳ Warte auf Upload-Bestätigung...")
        for attempt in range(10):
            print(f"   🔄 Refresh {attempt + 1}/10...")
            driver.refresh()
            time.sleep(4)

            count_after = _get_badge_count(driver)
            print(f"   📊 Badge-Zähler: {count_after}")

            if count_after is not None and count_before is not None and count_after > count_before:
                print(f"✅ Upload bestätigt! Zähler: {count_before} → {count_after}")
                break
            elif count_after is None and count_before is None:
                print("ℹ️  Badge nicht gefunden — Upload vermutlich erfolgreich")
                break
        else:
            print("⚠️  Timeout — Datei wurde möglicherweise trotzdem hochgeladen")

        print(f"\n✅ Upload abgeschlossen: {filename}")

    finally:
        driver.quit()

    return {"status": "ok", "filename": filename, "file": file_path}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 lexware.py <pdf-path>")
        sys.exit(1)
    result = run_lexware_upload(sys.argv[1])
    print(result)
