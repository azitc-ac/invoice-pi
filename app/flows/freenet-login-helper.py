#!/usr/bin/env python3
"""
Freenet Login-Skript
Speichert Credentials und Session in /pwdata/freenet/
Kein Timeout - du kannst so lange tippen wie du brauchst!
"""

import os
from playwright.sync_api import sync_playwright

PW_USERDATA = os.getenv("PW_USERDATA_FREENET", "/pwdata/freenet")
LOGIN_URL = "https://www.freenet-mobilfunk.de/onlineservice/meine-rechnungen"

print("\n" + "="*70)
print("🔐 FREENET LOGIN-HELPER")
print("="*70)
print(f"📁 Session wird gespeichert in: {PW_USERDATA}")
print(f"📍 URL: {LOGIN_URL}")
print("\n✅ Kein Timeout! Tippe in aller Ruhe ein.")
print("✅ Wenn eingeloggt → Ctrl+C drücken")
print("="*70 + "\n")

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
            headless=False,  # ← Sichtbares Fenster!
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-setuid-sandbox",
            ]
        )
        
        page = context.new_page()
        
        # Anti-WebDriver-Detection
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false,
            });
        """)
        
        print(f"🌐 Öffne {LOGIN_URL}...\n")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        
        print("⏳ Browser läuft... Logge dich manuell ein!")
        print("📝 Gib Username + Passwort ein")
        print("✅ Wenn eingeloggt, drücke Ctrl+C\n")
        
        # Warte endlos bis Ctrl+C
        import time
        while True:
            time.sleep(1)
        
except KeyboardInterrupt:
    print("\n\n✅ Einloggen erkannt!")
    print("✅ Session wurde in /pwdata/freenet/ gespeichert!")
    print("\nJetzt kannst du das Main-Script verwenden:")
    print("  python3 /app/flows/freenet.py\n")
