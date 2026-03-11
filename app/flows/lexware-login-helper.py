#!/usr/bin/env python3
"""
Lexware Login-Helper
Speichert Session in /pwdata/lexware/
Mit Anti-Bot-Detection Maßnahmen.
"""

import os
import time
from playwright.sync_api import sync_playwright

PW_USERDATA = os.getenv("PW_USERDATA_LEXWARE", "/pwdata/lexware")
LOGIN_URL    = "https://app.lexware.de"

LW_USER = os.getenv("LEXWARE_USERNAME", "")
LW_PASS = os.getenv("LEXWARE_PASSWORD", "")

print("\n" + "="*70)
print("🔐 LEXWARE LOGIN-HELPER")
print("="*70)
print(f"📁 Session wird gespeichert in: {PW_USERDATA}")
if LW_USER:
    print(f"👤 Username: {LW_USER}")
print("="*70 + "\n")

# Stale Locks entfernen
for lock_file in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
    lock_path = os.path.join(PW_USERDATA, lock_file)
    if os.path.exists(lock_path):
        os.remove(lock_path)
        print(f"🧹 Lock entfernt: {lock_path}")

try:
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PW_USERDATA,
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                # Anti-Detection
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-extensions",
                "--start-maximized",
            ],
            # Echter Browser-Fingerprint
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="de-DE",
            timezone_id="Europe/Berlin",
        )

        # Anti-Detection Scripts auf allen Seiten
        context.add_init_script("""
            // navigator.webdriver verstecken
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });

            // Chrome-Object simulieren (fehlt in Chromium)
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };

            // Plugins simulieren (echter Browser hat welche)
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    { name: 'Chrome PDF Plugin' },
                    { name: 'Chrome PDF Viewer' },
                    { name: 'Native Client' }
                ],
            });

            // Sprachen setzen
            Object.defineProperty(navigator, 'languages', {
                get: () => ['de-DE', 'de', 'en-US', 'en'],
            });

            // Permissions-Abfrage patchen
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : originalQuery(parameters)
            );
        """)

        page = context.new_page()

        print(f"🌐 Öffne {LOGIN_URL}...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        time.sleep(2)

        # Credentials vorausfüllen wenn vorhanden — mit echten Tastatur-Events
        if LW_USER and LW_PASS:
            print("🔐 Fülle Credentials ein (mit echten Keyboard-Events)...")
            try:
                # Email-Feld
                email_selectors = [
                    "input[type='email']",
                    "input[name='email']",
                    "input[id*='email']",
                    "input[id*='user']",
                    "input[placeholder*='E-Mail']",
                    "input[placeholder*='email']",
                ]
                for sel in email_selectors:
                    try:
                        el = page.locator(sel).first
                        if el.count() > 0 and el.is_visible():
                            el.click()
                            time.sleep(0.3)
                            # Echtes Tippen statt fill() — täuscht Anti-Bot-Systeme besser
                            el.type(LW_USER, delay=80)
                            print(f"✅ Username eingetippt ({sel})")
                            break
                    except Exception:
                        continue

                time.sleep(0.5)

                # Passwort-Feld
                pwd_el = page.locator("input[type='password']").first
                if pwd_el.count() > 0 and pwd_el.is_visible():
                    pwd_el.click()
                    time.sleep(0.3)
                    pwd_el.type(LW_PASS, delay=60)
                    print("✅ Passwort eingetippt")

                print("\n⚠️  Credentials eingetippt.")
                print("👉 Bitte jetzt manuell auf 'Anmelden' klicken!")
                print("   (Bewusst nicht automatisch — verhindert Bot-Erkennung)\n")

            except Exception as e:
                print(f"⚠️  Konnte Credentials nicht einfüllen: {e}")
                print("👉 Bitte manuell einloggen!\n")
        else:
            print("ℹ️  Keine Credentials in .env — bitte manuell einloggen.")

        print("🖥️  Browser bleibt offen. Nach erfolgreichem Login → Ctrl+C\n")

        while True:
            time.sleep(1)

except KeyboardInterrupt:
    print("\n✅ Session gespeichert in:", PW_USERDATA)
    print("✅ Du kannst jetzt den Upload verwenden.\n")
