import os
import re
import time
import subprocess
from pathlib import Path

LW_USER     = os.getenv("LEXWARE_USERNAME", "")
LW_PASS     = os.getenv("LEXWARE_PASSWORD", "")
FF_PROFILE  = os.getenv("FF_PROFILE_LEXWARE", "/pwdata/lexware-ff")
LEXWARE_URL = "https://app.lexware.de"
DISPLAY     = os.getenv("DISPLAY", ":0")
FF_BIN      = "/usr/bin/firefox"


def _run(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        env={**os.environ, "DISPLAY": DISPLAY}
    )


def _xdo(cmd: str) -> str:
    return _run(f"xdotool {cmd}").stdout.strip()


def _get_wid(timeout=20) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Firefox (Mozilla) Fenster suchen
        for search in ["--class firefox", "--class Firefox", "--name 'Mozilla Firefox'", "--name 'Firefox'"]:
            wids = _xdo(f"search --onlyvisible {search}").splitlines()
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
    time.sleep(0.2)


def _type(wid: str, text: str):
    # Per xdotool type — funktioniert gut in echtem Firefox
    safe = text.replace("'", "'\\''")
    _run(f"xdotool type --window {wid} --clearmodifiers --delay 80 '{safe}'")
    time.sleep(0.2)


def _get_url(wid: str) -> str:
    _focus(wid)
    _key(wid, "F6")
    time.sleep(0.4)
    _key(wid, "ctrl+a")
    time.sleep(0.2)
    _key(wid, "ctrl+c")
    time.sleep(0.3)
    _key(wid, "Escape")
    result = _run("xclip -selection clipboard -o 2>/dev/null || xsel --clipboard --output 2>/dev/null || echo ''")
    return result.stdout.strip()


def _wait_url(wid: str, contains: str = None, not_contains: str = None, timeout=45) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        url = _get_url(wid)
        print(f"   📍 URL: {url}")
        if contains and contains.lower() in url.lower():
            return url
        if not_contains and not_contains.lower() not in url.lower():
            return url
        time.sleep(3)
    return ""


def _click_pos(wid: str, x: int, y: int):
    _xdo(f"mousemove --window {wid} {x} {y}")
    time.sleep(0.2)
    _xdo(f"click --window {wid} 1")
    time.sleep(0.5)


def _screenshot(name="screen"):
    _run(f"import -window root /tmp/{name}.png 2>/dev/null || scrot /tmp/{name}.png 2>/dev/null")


def _kill_firefox():
    subprocess.run("pkill -f 'firefox.*lexware' 2>/dev/null; pkill -f '/usr/bin/firefox' 2>/dev/null", shell=True)
    time.sleep(1)


def run_lexware_upload(file_path: str, headless: bool = True) -> dict:
    """
    Lädt eine Datei als neuen Beleg in Lexware hoch.
    Nutzt echten Firefox (Mozilla APT) + xdotool.
    headless wird ignoriert — Firefox läuft immer auf DISPLAY.
    """

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Datei nicht gefunden: {file_path}")
    if not LW_USER or not LW_PASS:
        raise RuntimeError("LEXWARE_USERNAME und LEXWARE_PASSWORD müssen in .env gesetzt sein!")

    filename = os.path.basename(file_path)
    abs_path  = os.path.abspath(file_path)
    print(f"\n🚀 Starte Lexware Upload")
    print(f"📄 Datei: {abs_path}")
    print(f"🦊 Browser: {FF_BIN}")
    print(f"📁 Profil: {FF_PROFILE}")

    Path(FF_PROFILE).mkdir(parents=True, exist_ok=True)
    _kill_firefox()

    # ── Firefox starten ──────────────────────────────────────────
    print("🦊 Starte Firefox...")
    subprocess.Popen(
        f"DISPLAY={DISPLAY} {FF_BIN} --no-sandbox --profile {FF_PROFILE} --new-window '{LEXWARE_URL}'",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    wid = _get_wid(timeout=20)
    print(f"✅ Firefox gestartet (WID: {wid})")
    time.sleep(5)

    # ── Login prüfen ─────────────────────────────────────────────
    url = _get_url(wid)
    print(f"📍 Start-URL: {url}")

    if "signin" in url.lower() or "login" in url.lower() or "authenticate" in url.lower():
        print("🔐 Login erforderlich...")

        # Cookie-Banner wegklicken falls vorhanden
        # Wir suchen nach dem "Alle akzeptieren" Button per Maus-Position ist unzuverlässig
        # Besser: Tab+Enter zum ersten Button navigieren oder per Tastatur
        time.sleep(2)

        # Versuche Cookie-Banner per Tab+Leertaste zu akzeptieren
        # "Alle akzeptieren" ist meist der zweite/rechte Button
        _focus(wid)
        # Klick in die Mitte des Dialogs um Fokus zu setzen
        _key(wid, "Tab")
        time.sleep(0.3)
        _key(wid, "Tab")
        time.sleep(0.3)
        _key(wid, "Return")
        time.sleep(1)
        print("✅ Cookie-Banner behandelt")

        # Email-Feld: Tab zum ersten Formularfeld
        _focus(wid)
        _key(wid, "Tab")
        time.sleep(0.5)
        _type(wid, LW_USER)
        print(f"✅ Email eingegeben")

        # Tab → Passwort
        _key(wid, "Tab")
        time.sleep(0.3)
        _type(wid, LW_PASS)
        print("✅ Passwort eingegeben")

        # Enter → Anmelden
        _key(wid, "Return")
        print("✅ Anmelden gedrückt — warte auf Redirect...")

        final_url = _wait_url(wid, not_contains="signin", timeout=45)
        if not final_url or "signin" in final_url.lower() or "login" in final_url.lower():
            _kill_firefox()
            raise RuntimeError("Login fehlgeschlagen. Credentials prüfen.")

        print(f"✅ Eingeloggt! URL: {final_url}")
        time.sleep(3)
    else:
        print("✅ Bereits eingeloggt")

    # ── Playwright für Upload-Flow dranhängen ────────────────────
    # Echter Firefox für Login, Playwright-Steuerung für DOM-Interaktion
    # Da CDP nicht geht, nutzen wir xdotool für alles

    # ── "Neuen Beleg erfassen" klicken ───────────────────────────
    print('🖱️  Klicke "Neuen Beleg erfassen"...')
    # Per xdotool search nach Button-Text
    time.sleep(2)

    # Wir nutzen xdotool um nach dem Button-Text zu suchen und zu klicken
    # Das geht über accessibility tree oder direkt über Koordinaten nach Screenshot
    # Einfachster Weg: xdotool key für Tastatur-Navigation oder direkte Textsuche

    # Versuche den Button per xdotool search zu finden
    btn_wid = _xdo("search --sync --onlyvisible --name 'Neuen Beleg erfassen'")
    if not btn_wid:
        # Fallback: suche in accessibility
        result = _run("xdotool search --onlyvisible --class firefox")
        wids = result.stdout.strip().splitlines()
        if wids:
            wid = wids[-1]

    # Nutze JavaScript über URL-Leiste um Buttons zu finden und zu klicken
    # Das ist der zuverlässigste Weg ohne CDP
    _focus(wid)
    _key(wid, "F6")
    time.sleep(0.3)
    _key(wid, "ctrl+a")

    js_click_new = (
        "javascript:void(Array.from(document.querySelectorAll('button,a'))"
        ".find(e=>e.textContent.includes('Neuen Beleg erfassen'))?.click())"
    )
    _type(wid, js_click_new)
    _key(wid, "Return")
    time.sleep(2)
    print('✅ "Neuen Beleg erfassen" geklickt')

    # ── "Datei per Klick auswählen" ───────────────────────────────
    print('🖱️  Klicke Upload-Button...')
    _focus(wid)
    _key(wid, "F6")
    time.sleep(0.3)
    _key(wid, "ctrl+a")

    js_click_upload = (
        "javascript:void(Array.from(document.querySelectorAll('button,label,div'))"
        ".find(e=>e.textContent.includes('Datei per Klick'))?.click())"
    )
    _type(wid, js_click_upload)
    _key(wid, "Return")
    time.sleep(2)
    print('✅ Upload-Button geklickt')

    # ── File-Dialog mit xdotool befüllen ─────────────────────────
    print(f'📎 Warte auf File-Dialog...')
    time.sleep(1)

    # File-Dialog Fenster suchen
    deadline = time.time() + 10
    file_wid = None
    while time.time() < deadline:
        for search in ["--name 'File Upload'", "--name 'Datei hochladen'", "--name 'Open'", "--name 'Öffnen'"]:
            wids = _xdo(f"search --onlyvisible {search}").splitlines()
            if wids:
                file_wid = wids[-1]
                break
        if file_wid:
            break
        time.sleep(0.5)

    if file_wid:
        print(f"✅ File-Dialog gefunden (WID: {file_wid})")
        _focus(file_wid)
        time.sleep(0.3)
        _type(file_wid, abs_path)
        _key(file_wid, "Return")
    else:
        # Fallback: Pfad direkt tippen (Dialog hat Fokus)
        print("⚠️  File-Dialog nicht gefunden — tippe Pfad direkt...")
        time.sleep(0.5)
        _type(wid, abs_path)
        _key(wid, "Return")

    print(f'✅ Datei gesetzt: {filename}')
    time.sleep(3)

    # ── Warten auf Verarbeitung ───────────────────────────────────
    print('⏳ Warte auf Verarbeitung (15s)...')
    time.sleep(15)

    # ── Speichern-Button klicken ──────────────────────────────────
    print('🖱️  Klicke Speichern-Button...')
    _focus(wid)
    _key(wid, "F6")
    time.sleep(0.3)
    _key(wid, "ctrl+a")

    js_save = (
        "javascript:void(Array.from(document.querySelectorAll('button'))"
        ".find(e=>e.textContent.includes('SPEICHERN') && !e.disabled)?.click())"
    )
    _type(wid, js_save)
    _key(wid, "Return")
    time.sleep(1)
    print('✅ Speichern geklickt')

    # ── Dropdown öffnen ───────────────────────────────────────────
    print('🖱️  Öffne Dropdown...')
    time.sleep(1)
    _focus(wid)
    _key(wid, "F6")
    time.sleep(0.3)
    _key(wid, "ctrl+a")

    js_dropdown = (
        "javascript:void(Array.from(document.querySelectorAll('button'))"
        ".find(e=>e.getAttribute('aria-haspopup') && "
        "e.closest('div')?.querySelector('button[disabled]') === null)?.click())"
    )
    _type(wid, js_dropdown)
    _key(wid, "Return")
    time.sleep(1)

    # ── "Speichern und Schließen" ─────────────────────────────────
    print('🖱️  Klicke "Speichern und Schließen"...')
    _focus(wid)
    _key(wid, "F6")
    time.sleep(0.3)
    _key(wid, "ctrl+a")

    js_close = (
        "javascript:void(Array.from(document.querySelectorAll('li,button,a'))"
        ".find(e=>e.textContent.includes('Speichern und Schlie'))?.click())"
    )
    _type(wid, js_close)
    _key(wid, "Return")
    time.sleep(2)

    print(f'\n✅ Upload abgeschlossen: {filename}')
    _kill_firefox()

    return {"status": "ok", "filename": filename, "file": file_path}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 lexware.py <pdf-path>")
        sys.exit(1)
    result = run_lexware_upload(sys.argv[1])
    print(result)
