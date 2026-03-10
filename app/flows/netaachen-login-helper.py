#!/usr/bin/env python3
"""
NetAachen Login-Helper
Speichert Credentials und Session in /pwdata/netaachen/
KEIN Timeout - Login erfolgt direkt!
"""

import os
import time
from playwright.sync_api import sync_playwright

PW_USERDATA = os.getenv("PW_USERDATA_NETAACHEN", "/pwdata/netaachen")
LOGIN_URL = "https://sso.netcologne.de/cas/login?service=https://meinekundenwelt.netcologne.de/&mandant=na"

NA_USER = os.getenv("NETAACHEN_USERNAME", "")
NA_PASS = os.getenv("NETAACHEN_PASSWORD", "")

if not NA_USER or not NA_PASS:
    raise RuntimeError("NETAACHEN_USERNAME und NETAACHEN_PASSWORD müssen gesetzt sein!")

print("\n" + "="*70)
print("🔐 NETAACHEN LOGIN-HELPER")
print("="*70)
print(f"📁 Session wird gespeichert in: {PW_USERDATA}")
print(f"👤 Username: {NA_USER}")
print(f"\n🚀 Login läuft...\n")

try:
    # Stale Lock-Dateien entfernen
    import os as _os
    for lock_file in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        lock_path = _os.path.join(PW_USERDATA, lock_file)
        if _os.path.exists(lock_path):
            _os.remove(lock_path)
            print(f"🧹 Lock-Datei entfernt: {lock_path}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PW_USERDATA,
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
            ]
        )
        
        page = context.new_page()
        
        # Gehe zur Login-Seite
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        time.sleep(1)
        
        # Auto-Login
        print("🔐 Einloggen...")
        page.fill("input[id='username']", NA_USER)
        page.fill("input[id='password']", NA_PASS)
        page.click("input[type='submit'][value='Anmelden']")
        print("✅ Login-Formular abgesendet")
        
        # Warte auf Redirect
        print("⏳ Warte auf Login-Bestätigung...")
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except:
            pass
        
        time.sleep(2)
        print("✅ Eingeloggt!")
        
        # Dismiss Cookie Banner falls vorhanden
        print("🍪 Versuche Cookie-Banner zu schließen...")
        try:
            page.get_by_text("Alle akzeptieren").first.click()
            print("✅ Cookie-Banner geschlossen")
            time.sleep(1)
        except:
            print("⚠️  Kein Cookie-Banner")
        
        print("\n" + "="*70)
        print("✅ Session wurde gespeichert!")
        print("✅ Du kannst jetzt das Download-Script verwenden:")
        print("   python3 /app/flows/netaachen.py")
        print("="*70 + "\n")
        
        # Halte Browser offen bis Ctrl+C
        print("🖥️  Browser bleibt offen. Drücke Ctrl+C zum Beenden.\n")
        while True:
            time.sleep(1)
        
except KeyboardInterrupt:
    print("\n✅ Fertig!")
