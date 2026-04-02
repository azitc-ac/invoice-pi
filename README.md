# Invoice Pi

Automatisierter Rechnungsdownload und -upload als Docker-Container, optimiert für Raspberry Pi 4 (ARM64).

Unterstützte Dienste:
- **Freenet** – Mobilfunk-Rechnungen
- **NetAachen / NetCologne** – Internet & Telefon-Rechnungen
- **Lexware** – Upload heruntergeladener Rechnungen ins Buchhaltungssystem

---

## Architektur

```
FastAPI (Port 8000)
├── /download          → Playwright (Chromium, headless) lädt PDF herunter
├── /upload/lexware    → Playwright (Firefox) lädt PDF zu Lexware hoch
├── /session/init      → Manueller Browser-Login via noVNC (Port 8081)
├── /analyze/invoice   → PDF-Analyse (pdfplumber + Tesseract OCR)
└── /ws/logs           → Live-Log-Stream (WebSocket)

Scheduler (APScheduler)
├── 08:00 – Freenet Keep-Alive
└── 08:05 – NetAachen Keep-Alive
```

Sessions werden als Cookies in `./pwdata/<dienst>/playwright-storage.json` gespeichert und täglich per Keep-Alive aktualisiert.

---

## Schnellstart

```bash
cp .env.sample .env
# .env bearbeiten — Credentials eintragen

docker compose up --build -d
```

---

## Umgebungsvariablen

| Variable | Beschreibung | Beispiel |
|---|---|---|
| `FREENET_USERNAME` | Freenet Login-Email | `nutzer@example.com` |
| `FREENET_PASSWORD` | Freenet Passwort | |
| `NETAACHEN_USERNAME` | NetAachen Kundennummer / Email | |
| `NETAACHEN_PASSWORD` | NetAachen Passwort | |
| `LEXWARE_USERNAME` | Lexware Email | |
| `LEXWARE_PASSWORD` | Lexware Passwort | |
| `API_KEY` | Optionaler API-Key (Header: `X-API-Key`) | |
| `HEADLESS` | Browser unsichtbar (`true`) oder sichtbar via VNC (`false`) | `true` |
| `DOWNLOAD_DIR` | Zielverzeichnis für PDFs im Container | `/downloads` |
| `PW_USERDATA_FREENET` | Playwright-Profil Freenet | `/pwdata/freenet` |
| `PW_USERDATA_NETAACHEN` | Playwright-Profil NetAachen | `/pwdata/netaachen` |
| `PW_USERDATA_LEXWARE` | Playwright-Profil Lexware | `/pwdata/lexware` |
| `FF_PROFILE_LEXWARE` | Firefox-Profil für Lexware-Upload | `/pwdata/lexware-ff` |

---

## API-Endpunkte

### Rechnungsdownload

```bash
# Aktuelle Rechnung herunterladen
curl -X POST http://localhost:8000/download \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <key>" \
  -d '{"site": "freenet"}'

# Vormonat (month_offset=1)
curl -X POST http://localhost:8000/download \
  -H "Content-Type: application/json" \
  -d '{"site": "netaachen", "month_offset": 1}'
```

### Upload zu Lexware

```bash
# PDF als Binary-Body
curl -X POST "http://localhost:8000/upload/lexware?filename=Rechnung.pdf" \
  -H "Content-Type: application/pdf" \
  --data-binary @Rechnung.pdf

# Bereits im Container gespeicherte Datei
curl -X POST http://localhost:8000/upload/lexware/path \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/downloads/Rechnung_Freenet_2026-03.pdf"}'
```

### Session-Management

```bash
# Debug-Modus aktivieren (startet VNC)
curl -X POST http://localhost:8000/debug/enable

# Browser für manuellen Login öffnen (VNC erforderlich)
curl -X POST http://localhost:8000/session/init \
  -H "Content-Type: application/json" \
  -d '{"site": "netaachen", "save_session": true}'

# VNC im Browser: http://<host>:8081

# Keep-Alive manuell auslösen
curl -X POST http://localhost:8000/keepalive/netaachen
curl -X POST http://localhost:8000/keepalive/freenet
```

### Sonstiges

```bash
curl http://localhost:8000/health
curl http://localhost:8000/downloads/list
curl -X POST http://localhost:8000/cleanup/locks
```

---

## Volumes

| Host-Pfad | Container-Pfad | Inhalt |
|---|---|---|
| `./app` | `/app` | Anwendungscode |
| `./downloads` | `/downloads` | Heruntergeladene PDFs |
| `./pwdata` | `/pwdata` | Browser-Sessions & Cookies |
| `./logs` | `/var/log/supervisor` | Persistente Logs (10×10 MB, rotiert) |
| `/dev/shm` | `/dev/shm` | Shared Memory für Chromium |

---

## Session-Ablauf & Keep-Alive

NetAachen verwendet CAS/OAuth2-SSO (`sso.netcologne.de`). Die Session hat eine absolute Lebensdauer (serverseitig), die durch bloße Seitenbesuche nicht verlängert wird. Wenn der Keep-Alive einen abgelaufenen Login erkennt, erscheint eine Warnung im Log — danach ist ein manueller Re-Login über das Admin UI nötig:

1. `POST /debug/enable`
2. `POST /session/init` mit `{"site": "netaachen", "save_session": true}`
3. Im Browser via VNC auf **Anmelden** klicken
4. `POST /debug/disable`

---

## Logs

Live-Stream im Admin UI (`http://<host>:8000/admin`) oder via WebSocket:

```bash
# Letzten erfolgreichen NetAachen Keep-Alive finden
grep "NetAachen.*erfolgreich\|NetAachen.*fehlgeschlagen" ./logs/fastapi-stdout.log
```

---

## Security

- `.env` nicht committen
- `API_KEY` in der `.env` setzen, um alle Endpunkte abzusichern
- `/health`, `/admin` und `/ws/logs` sind ohne Key erreichbar
