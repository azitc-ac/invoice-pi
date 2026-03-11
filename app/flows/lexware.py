import os
import time
import shutil
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

LW_USER     = os.getenv("LEXWARE_USERNAME", "")
LW_PASS     = os.getenv("LEXWARE_PASSWORD", "")
FF_PROFILE  = os.getenv("FF_PROFILE_LEXWARE", "/pwdata/lexware-ff")
FF_BIN      = "/usr/bin/firefox"
LEXWARE_URL = "https://app.lexware.de"

TIMEOUT_NAV     = 30_000
TIMEOUT_ELEMENT = 15_000
TIMEOUT_UPLOAD  = 60_000


def _fresh_profile():
    if Path(FF_PROFILE).exists():
        shutil.rmtree(FF_PROFILE)
    Path(FF_PROFILE).mkdir(parents=True, exist_ok=True)
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
            headless=False,  # echter Firefox braucht Display
            args=["--no-sandbox"],
            viewport={"width": 1280, "height": 900},
            locale="de-DE",
            timezone_id="Europe/Berlin",
        )

        # Welcome-Tab schließen, Lexware-Tab nutzen
        page = ctx.new_page()
        print(f"📖 Öffne {LEXWARE_URL}...")
        page.goto(LEXWARE_URL, wait_until="domcontentloaded", timeout=TIMEOUT_NAV)
        time.sleep(4)

        # Welcome-Tabs schließen
        for p2 in ctx.pages:
            if p2 != page and "lexware" not in p2.url.lower():
                p2.close()

        print(f"📍 URL: {page.url}")
        print(f"🔍 navigator.webdriver: {page.evaluate('navigator.webdriver')}")

        # ── Cookie-Banner ─────────────────────────────────────────
        try:
            accept = _find(page, [
                "button:has-text('Alle akzeptieren')",
                "button:has-text('Accept all')",
                "button:has-text('Akzeptieren')",
            ], timeout=5_000)
            if accept:
                accept.click()
                print("✅ Cookie-Banner akzeptiert")
                time.sleep(1)
        except Exception:
            pass

        # ── Login ─────────────────────────────────────────────────
        if "signin" in page.url.lower() or "login" in page.url.lower() or "authenticate" in page.url.lower():
            print(f"🔐 Login als {LW_USER}...")

            # Email
            email_el = _find(page, [
                "input[type='email']",
                "input[name='email']",
                "input[placeholder*='Mail']",
            ], timeout=8_000)
            if not email_el:
                ctx.close()
                raise RuntimeError("Email-Feld nicht gefunden")
            email_el.click()
            email_el.fill(LW_USER)
            print("✅ Email gefüllt")
            time.sleep(0.3)

            # Passwort
            pwd_el = _find(page, ["input[type='password']"], timeout=5_000)
            if not pwd_el:
                ctx.close()
                raise RuntimeError("Passwort-Feld nicht gefunden")
            pwd_el.click()
            pwd_el.fill(LW_PASS)
            print("✅ Passwort gefüllt")
            time.sleep(0.3)

            # Anmelden
            btn = _find(page, [
                "button:has-text('Anmelden')",
                "button[type='submit']",
                "button:has-text('Login')",
            ], timeout=5_000)
            if not btn:
                ctx.close()
                raise RuntimeError("Anmelden-Button nicht gefunden")
            btn.click()
            print("✅ Anmelden geklickt — warte auf Redirect...")

            # Warten auf erfolgreichen Login
            deadline = time.time() + 30
            while time.time() < deadline:
                url = page.url
                if "signin" not in url.lower() and "login" not in url.lower() and "authenticate" not in url.lower():
                    print(f"✅ Eingeloggt! URL: {url}")
                    break
                if "403" in url or "forbidden" in url.lower():
                    ctx.close()
                    raise RuntimeError(f"403 Forbidden beim Login — WAF blockt")
                time.sleep(1)
            else:
                ctx.close()
                raise RuntimeError("Login-Timeout nach 30s")

            time.sleep(2)
        else:
            print("✅ Bereits eingeloggt")

        # ── "Neuen Beleg erfassen" ────────────────────────────────
        print('🖱️  Suche "Neuen Beleg erfassen"...')
        btn_new = _find(page, [
            "button:has-text('Neuen Beleg erfassen')",
            "a:has-text('Neuen Beleg erfassen')",
            "text=Neuen Beleg erfassen",
        ], timeout=TIMEOUT_ELEMENT)

        if not btn_new:
            ctx.close()
            raise RuntimeError('"Neuen Beleg erfassen" nicht gefunden')
        btn_new.click()
        print('✅ Geklickt')
        time.sleep(1)

        # ── Upload-Button ─────────────────────────────────────────
        print('🖱️  Suche Upload-Button...')
        btn_file = _find(page, [
            "button:has-text('Datei per Klick auswählen')",
            "text=Datei per Klick auswählen",
            "[class*='dropzone']",
            "[class*='drop-zone']",
            "label:has-text('Datei')",
        ], timeout=TIMEOUT_ELEMENT)

        if not btn_file:
            ctx.close()
            raise RuntimeError('"Datei per Klick auswählen" nicht gefunden')

        print(f'📎 Setze Datei: {filename}')
        try:
            with page.expect_file_chooser(timeout=10_000) as fc_info:
                btn_file.click()
            fc_info.value.set_files(abs_path)
            print('✅ Datei gesetzt')
        except PWTimeout:
            fi = page.locator("input[type='file']").first
            if fi.count() == 0:
                ctx.close()
                raise RuntimeError('Kein File-Input gefunden')
            fi.set_input_files(abs_path)
            print('✅ Datei via input[type=file] gesetzt')

        time.sleep(1)

        # ── Spinner abwarten ──────────────────────────────────────
        print('⏳ Warte auf Verarbeitung...')
        for sel in ["text=Beleg wird hochgeladen", "[class*='spinner']:visible"]:
            try:
                page.locator(sel).wait_for(state="visible", timeout=5_000)
                page.locator(sel).wait_for(state="hidden", timeout=TIMEOUT_UPLOAD)
                print('✅ Verarbeitung abgeschlossen')
                break
            except Exception:
                continue
        else:
            time.sleep(3)

        # ── Speichern-Button ──────────────────────────────────────
        print('⏳ Warte auf Speichern-Button...')
        save_btn = None
        deadline = time.time() + 60
        while time.time() < deadline:
            for sel in [
                "button:has-text('SPEICHERN + BELEGSTAPEL ABARBEITEN')",
                "button:has-text('Speichern + Belegstapel')",
                "button:has-text('SPEICHERN')",
            ]:
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible() and loc.is_enabled():
                        save_btn = loc
                        print('✅ Speichern-Button aktiv')
                        break
                except Exception:
                    continue
            if save_btn:
                break
            time.sleep(0.5)

        if not save_btn:
            ctx.close()
            raise RuntimeError('"SPEICHERN"-Button nicht gefunden')

        # ── Dropdown-Pfeil ────────────────────────────────────────
        print('🖱️  Suche Dropdown-Pfeil...')
        dropdown_btn = None
        for sel in [
            "button[aria-haspopup='true']:near(button:has-text('SPEICHERN'))",
            "button[aria-haspopup='menu']:near(button:has-text('SPEICHERN'))",
            "button[aria-haspopup='listbox']:near(button:has-text('SPEICHERN'))",
            "button[class*='dropdown']:near(button:has-text('SPEICHERN'))",
            "[class*='button-group'] button:last-child",
            "[class*='split-button'] button:last-child",
            "[class*='btn-group'] button:last-child",
        ]:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    if 'SPEICHERN + BELEGSTAPEL' not in (loc.text_content() or '').upper():
                        dropdown_btn = loc
                        print(f'✅ Dropdown: {sel}')
                        break
            except Exception:
                continue

        if not dropdown_btn:
            for xpath in ['xpath=..', 'xpath=../..']:
                try:
                    container = save_btn.locator(xpath)
                    btns = container.locator('button')
                    for i in range(btns.count() - 1, -1, -1):
                        c = btns.nth(i)
                        if 'SPEICHERN + BELEGSTAPEL' not in (c.text_content() or '').upper() and c.is_visible():
                            dropdown_btn = c
                            print(f'✅ Dropdown via {xpath}')
                            break
                    if dropdown_btn:
                        break
                except Exception:
                    continue

        if not dropdown_btn:
            ctx.close()
            raise RuntimeError('Dropdown-Pfeil nicht gefunden')

        dropdown_btn.click()
        print('✅ Dropdown geöffnet')
        time.sleep(0.8)

        # ── "Speichern und Schließen" ─────────────────────────────
        print('🖱️  Klicke "Speichern und Schließen"...')
        save_close = _find(page, [
            "text=Speichern und Schließen",
            "[role='menuitem']:has-text('Speichern und Schließen')",
            "[role='option']:has-text('Speichern und Schließen')",
            "li:has-text('Speichern und Schließen')",
            "button:has-text('Speichern und Schließen')",
        ], timeout=5_000)

        if not save_close:
            ctx.close()
            raise RuntimeError('"Speichern und Schließen" nicht gefunden')

        save_close.click()
        print('✅ "Speichern und Schließen" geklickt')
        time.sleep(2)

        print(f'\n✅ Upload erfolgreich: {filename}')
        ctx.close()

    return {"status": "ok", "filename": filename, "file": file_path}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 lexware.py <pdf-path>")
        sys.exit(1)
    result = run_lexware_upload(sys.argv[1])
    print(result)
