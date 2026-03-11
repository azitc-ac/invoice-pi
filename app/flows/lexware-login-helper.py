#!/usr/bin/env python3
"""
Lexware Login-Helper mit vollständigem Debug-Logging.
Zeigt Console-Errors, Network-Requests und JavaScript-Fehler beim Login.
"""

import os
import time
import json
from playwright.sync_api import sync_playwright

PW_USERDATA = os.getenv("PW_USERDATA_LEXWARE", "/pwdata/lexware")
LOGIN_URL    = "https://app.lexware.de"

LW_USER = os.getenv("LEXWARE_USERNAME", "")
LW_PASS = os.getenv("LEXWARE_PASSWORD", "")

print("\n" + "="*70)
print("🔐 LEXWARE LOGIN-HELPER (Debug-Modus)")
print("="*70)
print(f"📁 Session: {PW_USERDATA}")
print(f"👤 User:    {LW_USER or '(nicht gesetzt)'}")
print("="*70 + "\n")

# Locks entfernen
for lf in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
    p = os.path.join(PW_USERDATA, lf)
    if os.path.exists(p):
        os.remove(p)
        print(f"🧹 Lock entfernt: {p}")

try:
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PW_USERDATA,
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--start-maximized",
                # Remote debugging aktivieren für CDP
                "--remote-debugging-port=9222",
            ],
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="de-DE",
            timezone_id="Europe/Berlin",
        )

        # Anti-Detection
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['de-DE', 'de', 'en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    { name: 'Chrome PDF Plugin' },
                    { name: 'Chrome PDF Viewer' },
                    { name: 'Native Client' }
                ],
            });
        """)

        page = context.new_page()

        # ── Console Messages abfangen ────────────────────────────
        def on_console(msg):
            level = msg.type.upper()
            text  = msg.text
            # Nur relevante Meldungen zeigen
            if level in ("ERROR", "WARNING") or any(
                kw in text.lower() for kw in
                ["bot", "recaptcha", "captcha", "blocked", "forbidden",
                 "login", "auth", "token", "csrf", "error", "failed",
                 "unauthorized", "403", "401"]
            ):
                print(f"🖥️  CONSOLE [{level}]: {text}")

        page.on("console", on_console)

        # ── JavaScript-Exceptions abfangen ───────────────────────
        def on_pageerror(err):
            print(f"💥 JS-ERROR: {err}")

        page.on("pageerror", on_pageerror)

        # ── Netzwerk-Requests abfangen ───────────────────────────
        def on_request(req):
            # Nur API/Auth-Requests loggen, nicht alle Assets
            url = req.url
            if any(kw in url.lower() for kw in
                   ["api", "auth", "login", "token", "session",
                    "oauth", "saml", "sso", "captcha", "bot"]):
                print(f"📡 REQUEST  [{req.method}]: {url}")

        def on_response(resp):
            url  = resp.url
            status = resp.status
            if any(kw in url.lower() for kw in
                   ["api", "auth", "login", "token", "session",
                    "oauth", "saml", "sso", "captcha", "bot"]):
                icon = "✅" if status < 300 else "❌" if status >= 400 else "↪️"
                print(f"📡 RESPONSE [{status}] {icon}: {url}")
                # Bei Fehler-Responses Body versuchen zu lesen
                if status >= 400:
                    try:
                        body = resp.text()
                        if body and len(body) < 500:
                            print(f"   Body: {body}")
                    except Exception:
                        pass

        page.on("request",  on_request)
        page.on("response", on_response)

        # ── Seite laden ──────────────────────────────────────────
        print(f"🌐 Öffne {LOGIN_URL}...\n")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        time.sleep(2)

        # Aktuelle URL und Titel ausgeben
        print(f"📍 URL:   {page.url}")
        print(f"📄 Titel: {page.title()}")

        # Login-Formular analysieren
        print("\n🔍 Analysiere Login-Formular...")
        try:
            inputs = page.locator("input").all()
            print(f"   {len(inputs)} input-Felder gefunden:")
            for inp in inputs:
                try:
                    itype = inp.get_attribute("type") or "text"
                    iname = inp.get_attribute("name") or ""
                    iid   = inp.get_attribute("id") or ""
                    iph   = inp.get_attribute("placeholder") or ""
                    print(f"   → type={itype} name={iname} id={iid} placeholder={iph}")
                except Exception:
                    pass

            buttons = page.locator("button").all()
            print(f"\n   {len(buttons)} button(s) gefunden:")
            for btn in buttons:
                try:
                    btext = (btn.text_content() or "").strip()[:60]
                    btype = btn.get_attribute("type") or ""
                    bid   = btn.get_attribute("id") or ""
                    print(f"   → type={btype} id={bid} text={btext}")
                except Exception:
                    pass
        except Exception as e:
            print(f"   Analyse fehlgeschlagen: {e}")

        print(f"\n" + "="*70)
        print(f"👤 Username: {LW_USER}")
        print(f"🔑 Passwort: (siehe .env LEXWARE_PASSWORD)")
        print(f"")
        print(f"👉 Bitte jetzt manuell einloggen.")
        print(f"   Alle Netzwerk-Requests + Console-Errors werden geloggt.")
        print(f"   Nach Login → Ctrl+C")
        print(f"="*70 + "\n")

        while True:
            time.sleep(1)

except KeyboardInterrupt:
    print("\n✅ Session gespeichert:", PW_USERDATA)
