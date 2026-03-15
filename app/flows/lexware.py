import os
import asyncio
import shutil
import subprocess
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PWTimeout


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
    # Kein async nötig — nur Dateisystem-Operationen
    if Path(FF_PROFILE).exists():
        shutil.rmtree(FF_PROFILE)
    Path(FF_PROFILE).mkdir(parents=True, exist_ok=True)
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


async def _find(page, selectors, timeout=10_000):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=timeout)
            if await loc.is_visible():
                return loc
        except Exception:
            continue
    return None


async def _dismiss_cookie_banner(page):
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
    deadline = asyncio.get_event_loop().time() + 20
    while asyncio.get_event_loop().time() < deadline:
        # Hauptframe
        try:
            if await page.evaluate(js):
                print("✅ Cookie-Banner im Hauptframe geschlossen")
                await asyncio.sleep(0.6)
                return
        except Exception:
            pass

        # Alle iframes durchsuchen
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                print(f"   🔍 Prüfe iframe: {frame.url}")
                if await frame.evaluate(js):
                    print(f"✅ Cookie-Banner in iframe geschlossen: {frame.url}")
                    await asyncio.sleep(0.6)
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
                if await btn.is_visible(timeout=500):
                    await btn.click()
                    print(f"✅ Cookie-Banner per Locator geschlossen: {sel}")
                    await asyncio.sleep(0.6)
                    return
            except Exception:
                pass

        await asyncio.sleep(0.3)
    print("ℹ️  Kein Cookie-Banner gefunden")


async def _get_badge_count(page):
    js = """
var el = document.querySelector("span.grld-bs-badge-sidebar.grld-bs-badge-info, span.grld-bs-badge-info");
if (el) return parseInt(el.textContent.trim(), 10);
return null;
"""
    # Hauptframe
    try:
        result = await page.evaluate(js)
        if result is not None:
            return result
    except Exception:
        pass
    # Alle iframes durchsuchen
    for frame in page.frames:
        try:
            result = await frame.evaluate(js)
            if result is not None:
                return result
        except Exception:
            pass
    return None


async def run_lexware_upload(file_path: str, headless: bool = True) -> dict:
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Datei nicht gefunden: {file_path}")
    if not LW_USER or not LW_PASS:
        raise RuntimeError("LEXWARE_USERNAME und LEXWARE_PASSWORD müssen gesetzt sein!")

    filename = os.path.basename(file_path)
    abs_path  = os.path.abspath(file_path)
    print(f"\n🚀 Starte Lexware Upload v29")
    print(f"📄 Datei: {abs_path}")

    _fresh_profile()

    subprocess.run("pkill -f 'chrome-linux/chrome' 2>/dev/null", shell=True)
    await asyncio.sleep(1)

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

    await asyncio.sleep(4)

    async with async_playwright() as p:
        print(f"🔌 Verbinde via CDP...")
        browser = await p.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.bring_to_front()

        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        await asyncio.sleep(2)
        print(f"📍 URL: {page.url}")
        print(f"🔍 navigator.webdriver: {await page.evaluate('navigator.webdriver')}")

        print("⏳ Warte auf Login-Formular...")
        try:
            await page.wait_for_selector("input[type='email'], input[type='password'], input[name='username']", timeout=15_000)
        except Exception:
            pass
        await asyncio.sleep(1)

        print("⏳ Warte auf Cookie-Banner...")
        await asyncio.sleep(2)

        buttons = await page.evaluate("""
Array.from(document.querySelectorAll('button, a, [role="button"]'))
    .map(e => e.innerText || e.textContent || '')
    .filter(t => t.trim())
    .map(t => t.trim().substring(0, 60))
""")
        print(f"🔍 Sichtbare Buttons: {buttons[:15]}")

        await _dismiss_cookie_banner(page)

        # ── Login ─────────────────────────────────────────────────
        if any(x in page.url.lower() for x in ["signin", "login", "authenticate"]):
            print(f"🔐 Login als {LW_USER}...")
            email_el = await _find(page, [
                "input[type='email']",
                "input[name='email']",
                "input[name='username']",
                "input[autocomplete='username']",
            ], timeout=8_000)
            if not email_el:
                raise RuntimeError("Email-Feld nicht gefunden")
            await email_el.click()
            await email_el.fill(LW_USER)
            print("✅ Email gefüllt")
            await asyncio.sleep(0.3)

            pwd_el = await _find(page, ["input[type='password']"], timeout=5_000)
            if not pwd_el:
                raise RuntimeError("Passwort-Feld nicht gefunden")
            await pwd_el.click()
            await pwd_el.fill(LW_PASS)
            print("✅ Passwort gefüllt")
            await asyncio.sleep(0.3)

            btn = await _find(page, [
                "button:has-text('Anmelden')",
                "button[type='submit']",
                "button:has-text('Login')",
            ], timeout=5_000)
            if btn:
                print(f"🖱️  Klicke: '{await btn.text_content()}'")
                await btn.click()
            else:
                await pwd_el.press("Enter")
            print("⏳ Warte auf Redirect...")

            deadline = asyncio.get_event_loop().time() + 120
            while asyncio.get_event_loop().time() < deadline:
                try:
                    url = await page.evaluate("window.location.href")
                except Exception:
                    url = page.url
                print(f"📍 URL check: {url}")
                if "dashboard" in url.lower() or "voucher" in url.lower() or "belege" in url.lower():
                    print(f"✅ Eingeloggt!")
                    break
                if "403" in url or "forbidden" in url.lower():
                    raise RuntimeError(f"403 Forbidden")
                await asyncio.sleep(2)
            else:
                raise RuntimeError(f"Login-Timeout. URL: {page.url}")

            await asyncio.sleep(3)
        else:
            print("✅ Bereits eingeloggt")

        # ── Direkt zur Voucher-URL navigieren ───
        print(f"📖 Navigiere direkt zu Voucher-Editor...")
        try:
            await page.goto(LEXWARE_VOUCHER_URL, wait_until="commit", timeout=15_000)
        except Exception as e:
            print(f"⚠️  goto Exception (ignoriert): {e}")
        await asyncio.sleep(3)
        print(f"📍 URL: {await page.evaluate('window.location.href')}")

        # ── File-Input ────────────────────────────────────────────
        print("🖱️  Suche File-Input...")
        await asyncio.sleep(2)

        fi = None
        deadline = asyncio.get_event_loop().time() + 30
        while asyncio.get_event_loop().time() < deadline:
            try:
                loc = page.locator("input[type='file']").first
                await loc.wait_for(state="attached", timeout=1000)
                fi = loc
                print("✅ File-Input gefunden")
                break
            except Exception:
                pass
            await asyncio.sleep(0.5)

        if not fi:
            raise RuntimeError("File-Input nicht gefunden")

        await page.evaluate("""
var el = document.querySelector("input[type='file']");
if (el) {
    el.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;width:100px!important;height:30px!important;';
    el.removeAttribute('hidden');
    el.removeAttribute('aria-hidden');
    el.removeAttribute('disabled');
}
""")
        await asyncio.sleep(0.3)

        count_before = await _get_badge_count(page)
        print(f"📊 Badge-Zähler vor Upload: {count_before}")

        await fi.set_input_files(abs_path)
        print(f"✅ Datei gesetzt: {filename}")
        await asyncio.sleep(3)

        # ── Bestätigung: Voucher-URL neu laden und Badge prüfen ──
        print("⏳ Warte 3s dann Voucher-URL neu laden...")
        await asyncio.sleep(3)
        try:
            await page.goto(LEXWARE_VOUCHER_URL, wait_until="commit", timeout=15_000)
        except Exception:
            pass
        await asyncio.sleep(5)

        # Badge direkt per JS lesen
        badge_js = "document.querySelector('span.grld-bs-badge-sidebar.grld-bs-badge-info')?.textContent?.trim()"
        count_after = None
        for frame in [page.main_frame] + page.frames:
            try:
                val = await frame.evaluate(badge_js)
                print(f"   🔍 Frame {frame.url[:50]}: badge={val}")
                if val is not None:
                    count_after = int(val)
                    break
            except Exception as e:
                print(f"   ⚠️  Frame error: {e}")

        print(f"📊 Badge nach Upload: {count_after}")
        if count_after is not None and (count_before is None or count_after > count_before):
            print(f"✅ Upload bestätigt! Badge: {count_after}")
        else:
            print("⚠️  Badge unverändert — Upload möglicherweise trotzdem erfolgreich")

        print(f"\n✅ Upload abgeschlossen: {filename}")
        await browser.close()

    proc.terminate()
    return {"status": "ok", "filename": filename, "file": file_path}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 lexware.py <pdf-path>")
        sys.exit(1)
    result = asyncio.run(run_lexware_upload(sys.argv[1]))
    print(result)
