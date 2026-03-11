import os
import time
import subprocess
from pathlib import Path

LW_USER     = os.getenv("LEXWARE_USERNAME", "")
LW_PASS     = os.getenv("LEXWARE_PASSWORD", "")
LEXWARE_URL = "https://app.lexware.de"
DISPLAY     = os.getenv("DISPLAY", ":0")
FF_PROFILE  = os.getenv("FF_PROFILE_LEXWARE", "/pwdata/lexware-real")


def _xdo(cmd: str, check=False) -> str:
    result = subprocess.run(
        f"xdotool {cmd}", shell=True, capture_output=True, text=True,
        env={**os.environ, "DISPLAY": DISPLAY}
    )
    return result.stdout.strip()


def _run(cmd: str) -> str:
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        env={**os.environ, "DISPLAY": DISPLAY}
    )
    return result.stdout.strip()


def _get_firefox_wid(timeout=20) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        wids = _xdo("search --onlyvisible --class firefox").splitlines()
        if wids:
            return wids[-1]
        time.sleep(0.5)
    raise RuntimeError("Firefox-Fenster nicht erschienen")


def _focus(wid: str):
    _xdo(f"windowfocus --sync {wid}")
    _xdo(f"windowraise {wid}")
    time.sleep(0.3)


def _key(wid: str, key: str):
    _xdo(f"key --window {wid} --clearmodifiers {key}")
    time.sleep(0.15)


def _type(wid: str, text: str):
    # Zeichen für Zeichen tippen — zuverlässiger für Sonderzeichen
    for ch in text:
        escaped = ch.replace("'", "'\\''")
        _xdo(f"type --window {wid} --clearmodifiers --delay 100 '{escaped}'")


def _get_url(wid: str) -> str:
    _focus(wid)
    _key(wid, "F6")
    time.sleep(0.4)
    _key(wid, "ctrl+a")
    time.sleep(0.2)
    _key(wid, "ctrl+c")
    time.sleep(0.3)
    _key(wid, "Escape")
    url = _run("xclip -selection clipboard -o 2>/dev/null || xsel --clipboard --output 2>/dev/null || echo ''")
    return url.strip()


def _wait_url_change(wid: str, away_from: str, timeout=45) -> str:
    """Warten bis URL sich von 'away_from' wegbewegt."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        url = _get_url(wid)
        print(f"   URL: {url}")
        if away_from.lower() not in url.lower():
            return url
        time.sleep(3)
    return ""


def _login_with_xdotool(wid: str):
    """Login-Formular mit xdotool ausfüllen."""
    print(f"🔐 Fülle Login-Formular aus...")
    _focus(wid)
    time.sleep(1)

    # Seite neu laden für frisches WAF-Challenge
    _key(wid, "F5")
    time.sleep(4)

    # In Email-Feld klicken — Tab von Anfang
    # Erst Fokus auf Seite sicherstellen
    _key(wid, "Escape")
    time.sleep(0.2)

    # Tab bis Email-Feld (normalerweise erstes Formularfeld)
    _key(wid, "Tab")
    time.sleep(0.4)

    # Email eingeben
    _type(wid, LW_USER)
    time.sleep(0.3)

    # Tab → Passwort
    _key(wid, "Tab")
    time.sleep(0.3)

    # Passwort eingeben
    _type(wid, LW_PASS)
    time.sleep(0.3)

    # Enter → Anmelden
    _key(wid, "Return")
    print("✅ Formular abgesendet")


def run_lexware_upload(file_path: str, headless: bool = True) -> dict:
    """
    Lädt eine Datei als neuen Beleg in Lexware hoch.
    Phase 1: Echter firefox via xdotool für den Login (kein Playwright-Fingerprint)
    Phase 2: Playwright-Firefox mit gespeicherter Session für den Upload-Flow
    """

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Datei nicht gefunden: {file_path}")
    if not LW_USER or not LW_PASS:
        raise RuntimeError("LEXWARE_USERNAME und LEXWARE_PASSWORD müssen in .env gesetzt sein!")

    filename = os.path.basename(file_path)
    abs_path  = os.path.abspath(file_path)
    print(f"\n🚀 Starte Lexware Upload")
    print(f"📄 Datei: {abs_path}")

    Path(FF_PROFILE).mkdir(parents=True, exist_ok=True)

    # Alte Firefox-Instanzen killen
    subprocess.run("pkill -f firefox 2>/dev/null", shell=True)
    time.sleep(1)

    # ── Phase 1: Echter Firefox für Login ───────────────────────
    print("🦊 Starte echten Firefox für Login...")
    subprocess.Popen(
        f"DISPLAY={DISPLAY} firefox --profile {FF_PROFILE} --new-window '{LEXWARE_URL}'",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    try:
        wid = _get_firefox_wid(timeout=20)
        print(f"✅ Firefox gestartet (WID: {wid})")
        time.sleep(5)

        url = _get_url(wid)
        print(f"📍 Start-URL: {url}")

        if "login" in url.lower() or "signin" in url.lower() or "authenticate" in url.lower():
            _login_with_xdotool(wid)

            print("⏳ Warte auf Login-Erfolg...")
            final_url = _wait_url_change(wid, "signin", timeout=45)
            if not final_url:
                final_url = _wait_url_change(wid, "login", timeout=15)

            if not final_url or "login" in final_url.lower() or "signin" in final_url.lower():
                raise RuntimeError("Login fehlgeschlagen — bitte Credentials prüfen.")

            print(f"✅ Eingeloggt! URL: {final_url}")
            # Kurz eingeloggt bleiben damit Session-Cookies gespeichert werden
            time.sleep(5)
        else:
            print("✅ Bereits eingeloggt")

    finally:
        subprocess.run("pkill -f firefox 2>/dev/null", shell=True)
        time.sleep(2)

    # ── Phase 2: Playwright-Firefox für Upload-Flow ──────────────
    print("🔄 Starte Playwright-Firefox für Upload...")

    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    # Lock-Dateien entfernen
    for lf in ["lock", ".parentlock"]:
        lp = os.path.join(FF_PROFILE, lf)
        if os.path.exists(lp):
            os.remove(lp)
            print(f"🧹 Lock entfernt: {lp}")

    with sync_playwright() as p:
        context = p.firefox.launch_persistent_context(
            user_data_dir=FF_PROFILE,
            headless=False,
            args=[],
            viewport={"width": 1280, "height": 900},
            locale="de-DE",
            timezone_id="Europe/Berlin",
            accept_downloads=False,
        )

        page = context.new_page()
        print(f"📖 Öffne {LEXWARE_URL}...")
        page.goto(LEXWARE_URL, wait_until="domcontentloaded", timeout=20_000)
        time.sleep(3)

        current_url = page.url
        print(f"📍 URL: {current_url}")

        if "login" in current_url.lower() or "signin" in current_url.lower():
            context.close()
            raise RuntimeError("Session nicht übertragen — bitte erneut versuchen.")

        # ── "Neuen Beleg erfassen" ────────────────────────────────
        print('🖱️  Klicke "Neuen Beleg erfassen"...')
        btn_new = None
        for sel in [
            "button:has-text('Neuen Beleg erfassen')",
            "a:has-text('Neuen Beleg erfassen')",
            "text=Neuen Beleg erfassen",
        ]:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=10_000)
                btn_new = loc
                break
            except Exception:
                continue

        if btn_new is None:
            context.close()
            raise RuntimeError('"Neuen Beleg erfassen" nicht gefunden.')

        btn_new.click()
        print('✅ Geklickt')
        time.sleep(1)

        # ── "Datei per Klick auswählen" ───────────────────────────
        print('🖱️  Suche "Datei per Klick auswählen"...')
        btn_file = None
        for sel in [
            "button:has-text('Datei per Klick auswählen')",
            "text=Datei per Klick auswählen",
            "[class*='dropzone']",
            "[class*='drop-zone']",
            "label:has-text('Datei')",
        ]:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=10_000)
                btn_file = loc
                break
            except Exception:
                continue

        if btn_file is None:
            context.close()
            raise RuntimeError('"Datei per Klick auswählen" nicht gefunden.')

        print(f'📎 Setze Datei: {filename}')
        try:
            with page.expect_file_chooser(timeout=10_000) as fc_info:
                btn_file.click()
            fc_info.value.set_files(abs_path)
            print('✅ Datei gesetzt')
        except PWTimeout:
            fi = page.locator("input[type='file']").first
            if fi.count() == 0:
                context.close()
                raise RuntimeError('Kein File-Input gefunden.')
            fi.set_input_files(abs_path)
            print('✅ Datei via input[type=file] gesetzt')

        time.sleep(1)

        # ── Spinner abwarten ──────────────────────────────────────
        print('⏳ Warte auf Verarbeitung...')
        for sel in ["text=Beleg wird hochgeladen", "[class*='spinner']:visible"]:
            try:
                page.locator(sel).wait_for(state="visible", timeout=5_000)
                page.locator(sel).wait_for(state="hidden", timeout=60_000)
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
                        print(f'✅ Speichern-Button aktiv')
                        break
                except Exception:
                    continue
            if save_btn:
                break
            time.sleep(0.5)

        if save_btn is None:
            context.close()
            raise RuntimeError('"SPEICHERN"-Button nicht gefunden.')

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

        if dropdown_btn is None:
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

        if dropdown_btn is None:
            context.close()
            raise RuntimeError('Dropdown-Pfeil nicht gefunden.')

        dropdown_btn.click()
        print('✅ Dropdown geöffnet')
        time.sleep(0.8)

        # ── "Speichern und Schließen" ─────────────────────────────
        print('🖱️  Klicke "Speichern und Schließen"...')
        save_close = None
        for sel in [
            "text=Speichern und Schließen",
            "[role='menuitem']:has-text('Speichern und Schließen')",
            "[role='option']:has-text('Speichern und Schließen')",
            "li:has-text('Speichern und Schließen')",
            "button:has-text('Speichern und Schließen')",
        ]:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=5_000)
                save_close = loc
                break
            except Exception:
                continue

        if save_close is None:
            context.close()
            raise RuntimeError('"Speichern und Schließen" nicht gefunden.')

        save_close.click()
        print('✅ "Speichern und Schließen" geklickt')
        time.sleep(2)

        print(f'\n✅ Upload erfolgreich: {filename}')
        context.close()

    return {
        "status": "ok",
        "filename": filename,
        "file": file_path,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 lexware.py <pdf-path>")
        sys.exit(1)
    result = run_lexware_upload(sys.argv[1])
    print(result)
