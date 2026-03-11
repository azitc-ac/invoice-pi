import os
import time
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PW_USERDATA = os.getenv("PW_USERDATA_LEXWARE", "/pwdata/lexware")
LEXWARE_URL = "https://lexware.de"

TIMEOUT_NAVIGATION   = 20_000
TIMEOUT_ELEMENT      = 15_000
TIMEOUT_UPLOAD_DONE  = 60_000
TIMEOUT_FILE_CHOOSER = 10_000


def _remove_locks():
    for lock_file in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        lock_path = os.path.join(PW_USERDATA, lock_file)
        if os.path.exists(lock_path):
            os.remove(lock_path)
            print(f"🧹 Lock entfernt: {lock_path}")


def _find_element(page, selectors: list, timeout: int = 10_000):
    """Probiert Selektoren durch, gibt ersten sichtbaren Treffer zurück oder None."""
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
    """
    Lädt eine Datei als neuen Beleg in Lexware hoch.

    Ablauf:
      1. Navigiere zu Lexware (Session aus /pwdata/lexware)
      2. Klick "Neuen Beleg erfassen"
      3. Klick "Datei per Klick auswählen" -> File-Chooser -> Datei setzen
      4. Warten bis Spinner "Beleg wird hochgeladen" verschwindet
      5. Warten bis "SPEICHERN + BELEGSTAPEL ABARBEITEN" aktiv wird
      6. Klick auf Dropdown-Pfeil direkt neben dem Button
      7. Klick "Speichern und Schließen"
    """

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Datei nicht gefunden: {file_path}")

    filename = os.path.basename(file_path)
    print(f"\n🚀 Starte Lexware Upload (headless={headless})")
    print(f"📄 Datei: {file_path}")
    print(f"📁 User Data Dir: {PW_USERDATA}")

    _remove_locks()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PW_USERDATA,
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-setuid-sandbox",
                "--disable-infobars",
            ],
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="de-DE",
            timezone_id="Europe/Berlin",
            accept_downloads=False,
        )

        # Anti-Bot-Detection
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['de-DE', 'de', 'en-US', 'en'] });
        """)

        page = context.new_page()

        # ── 1. Navigation ────────────────────────────────────────
        print(f"📖 Öffne {LEXWARE_URL} ...")
        page.goto(LEXWARE_URL, wait_until="domcontentloaded", timeout=TIMEOUT_NAVIGATION)
        time.sleep(2)
        print("✅ Seite geladen, nutze gespeicherte Session")

        # ── 2. "Neuen Beleg erfassen" klicken ────────────────────
        print('🖱️  Suche "Neuen Beleg erfassen"...')
        btn_new = _find_element(page, [
            "button:has-text('Neuen Beleg erfassen')",
            "a:has-text('Neuen Beleg erfassen')",
            "text=Neuen Beleg erfassen",
        ], timeout=TIMEOUT_ELEMENT)

        if btn_new is None:
            context.close()
            raise RuntimeError(
                '"Neuen Beleg erfassen" nicht gefunden. '
                'Ist die Lexware-Session noch gültig? -> POST /session/init mit site=lexware'
            )

        btn_new.click()
        print('✅ "Neuen Beleg erfassen" geklickt')
        time.sleep(1)

        # ── 3a. "Datei per Klick auswählen" finden ───────────────
        print('🖱️  Suche "Datei per Klick auswählen"...')
        btn_file = _find_element(page, [
            "button:has-text('Datei per Klick auswählen')",
            "text=Datei per Klick auswählen",
            "[class*='upload']:has-text('Klick')",
            "[class*='dropzone']",
            "[class*='drop-zone']",
            "label:has-text('Datei')",
        ], timeout=TIMEOUT_ELEMENT)

        if btn_file is None:
            context.close()
            raise RuntimeError('"Datei per Klick auswählen" nicht gefunden.')

        # ── 3b. File-Chooser abfangen & Datei setzen ─────────────
        print(f'📎 Öffne File-Chooser und setze: {filename}')
        try:
            with page.expect_file_chooser(timeout=TIMEOUT_FILE_CHOOSER) as fc_info:
                btn_file.click()
            file_chooser = fc_info.value
            file_chooser.set_files(file_path)
            print(f'✅ Datei gesetzt: {filename}')
        except PWTimeout:
            # Fallback: verstecktes input[type=file] direkt befüllen
            print('⚠️  File-Chooser nicht erschienen — Fallback auf input[type=file]...')
            file_input = page.locator("input[type='file']").first
            if file_input.count() == 0:
                context.close()
                raise RuntimeError('Weder File-Chooser noch input[type=file] gefunden.')
            file_input.set_input_files(file_path)
            print(f'✅ Datei via input[type=file] gesetzt: {filename}')

        time.sleep(1)

        # ── 4. Warten bis Spinner "Beleg wird hochgeladen" weg ───
        print('⏳ Warte auf Spinner "Beleg wird hochgeladen"...')
        spinner_selectors = [
            "text=Beleg wird hochgeladen",
            "[class*='spinner']:visible",
            "[class*='loading']:visible",
            "[class*='progress']:visible",
        ]

        spinner_appeared = False
        for sel in spinner_selectors:
            try:
                page.locator(sel).wait_for(state="visible", timeout=5_000)
                print(f'   Spinner sichtbar ({sel})')
                spinner_appeared = True
                page.locator(sel).wait_for(state="hidden", timeout=TIMEOUT_UPLOAD_DONE)
                print('✅ Spinner verschwunden — Verarbeitung abgeschlossen')
                break
            except Exception:
                continue

        if not spinner_appeared:
            print('   (Kein Spinner erkannt — Upload möglicherweise sofort fertig)')
            time.sleep(2)

        # ── 5. Warten bis "SPEICHERN + BELEGSTAPEL ABARBEITEN" aktiv ──
        print('⏳ Warte bis Speichern-Button aktiv wird...')
        save_btn_selectors = [
            "button:has-text('SPEICHERN + BELEGSTAPEL ABARBEITEN')",
            "button:has-text('Speichern + Belegstapel')",
            "button:has-text('SPEICHERN')",
        ]

        save_btn = None
        deadline = time.time() + (TIMEOUT_UPLOAD_DONE / 1000)

        while time.time() < deadline:
            for sel in save_btn_selectors:
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible() and loc.is_enabled():
                        save_btn = loc
                        print(f'✅ Speichern-Button aktiv: {sel}')
                        break
                except Exception:
                    continue
            if save_btn:
                break
            time.sleep(0.5)

        if save_btn is None:
            context.close()
            raise RuntimeError(
                '"SPEICHERN + BELEGSTAPEL ABARBEITEN" nicht gefunden oder nicht aktiv. '
                'Upload möglicherweise fehlgeschlagen.'
            )

        # ── 6. Dropdown-Pfeil neben Speichern-Button klicken ─────
        #
        # Lexware nutzt ein Split-Button-Muster:
        #   [ SPEICHERN + BELEGSTAPEL ABARBEITEN ][ ▼ ]
        # Beide Buttons liegen in einem gemeinsamen Container.
        # Wir suchen den letzten Button im gleichen Parent.
        #
        print('🖱️  Suche Dropdown-Pfeil neben Speichern-Button...')
        dropdown_btn = None

        # Versuch 1: explizite Selektoren
        dropdown_selectors = [
            "button[aria-haspopup='true']:near(button:has-text('SPEICHERN'))",
            "button[aria-haspopup='menu']:near(button:has-text('SPEICHERN'))",
            "button[aria-haspopup='listbox']:near(button:has-text('SPEICHERN'))",
            "button[aria-label*='dropdown']:near(button:has-text('SPEICHERN'))",
            "button[aria-label*='Dropdown']:near(button:has-text('SPEICHERN'))",
            "button[class*='dropdown']:near(button:has-text('SPEICHERN'))",
            "button[class*='split']:near(button:has-text('SPEICHERN'))",
            "button[class*='caret']:near(button:has-text('SPEICHERN'))",
            "[class*='button-group'] button:last-child",
            "[class*='split-button'] button:last-child",
            "[class*='btn-group'] button:last-child",
        ]

        for sel in dropdown_selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    # Sicherstellen dass wir nicht den Speichern-Button selbst erwischen
                    text = loc.text_content() or ''
                    if 'SPEICHERN + BELEGSTAPEL' not in text.upper():
                        dropdown_btn = loc
                        print(f'✅ Dropdown gefunden: {sel}')
                        break
            except Exception:
                continue

        # Versuch 2: letzter Button im Parent-Container des Speichern-Buttons
        if dropdown_btn is None:
            print('   Fallback: suche im Parent-Container des Speichern-Buttons...')
            try:
                parent = save_btn.locator('xpath=..')
                btns = parent.locator('button')
                count = btns.count()
                print(f'   Buttons im Parent: {count}')
                if count >= 2:
                    last = btns.last
                    text = last.text_content() or ''
                    if 'SPEICHERN + BELEGSTAPEL' not in text.upper():
                        dropdown_btn = last
                        print('✅ Dropdown via Parent (letzter Button)')
                    else:
                        # Hauptbutton hat keinen getrennten Dropdown — direkt klicken
                        print('   Nur ein Button im Parent — kein separater Dropdown-Pfeil')
                        dropdown_btn = None
            except Exception as e:
                print(f'   Parent-Fallback fehlgeschlagen: {e}')

        # Versuch 3: Grandparent (manche Frameworks wrappen noch eine Ebene tiefer)
        if dropdown_btn is None:
            print('   Fallback: Grandparent-Ebene...')
            try:
                grandparent = save_btn.locator('xpath=../..')
                btns = grandparent.locator('button')
                count = btns.count()
                print(f'   Buttons im Grandparent: {count}')
                if count >= 2:
                    for i in range(count - 1, -1, -1):
                        candidate = btns.nth(i)
                        text = candidate.text_content() or ''
                        if 'SPEICHERN + BELEGSTAPEL' not in text.upper() and candidate.is_visible():
                            dropdown_btn = candidate
                            print(f'✅ Dropdown via Grandparent (Button {i})')
                            break
            except Exception as e:
                print(f'   Grandparent-Fallback fehlgeschlagen: {e}')

        if dropdown_btn is None:
            context.close()
            raise RuntimeError(
                'Dropdown-Pfeil neben "SPEICHERN + BELEGSTAPEL ABARBEITEN" nicht gefunden. '
                'Bitte im VNC-Modus prüfen und Selektoren in lexware.py anpassen.'
            )

        dropdown_btn.click()
        print('✅ Dropdown geöffnet')
        time.sleep(0.8)

        # ── 7. "Speichern und Schließen" im Dropdown klicken ─────
        print('🖱️  Suche "Speichern und Schließen"...')
        save_close = _find_element(page, [
            "text=Speichern und Schließen",
            "[role='menuitem']:has-text('Speichern und Schließen')",
            "[role='option']:has-text('Speichern und Schließen')",
            "li:has-text('Speichern und Schließen')",
            "button:has-text('Speichern und Schließen')",
            "a:has-text('Speichern und Schließen')",
        ], timeout=5_000)

        if save_close is None:
            context.close()
            raise RuntimeError('"Speichern und Schließen" im Dropdown nicht gefunden.')

        save_close.click()
        print('✅ "Speichern und Schließen" geklickt')
        time.sleep(2)

        print(f'\n✅ Upload erfolgreich abgeschlossen: {filename}')
        context.close()

        return {
            "status": "ok",
            "filename": filename,
            "file": file_path,
        }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 lexware.py <pdf-path> [--gui]")
        sys.exit(1)
    headless = "--gui" not in sys.argv
    result = run_lexware_upload(sys.argv[1], headless=headless)
    print(result)
