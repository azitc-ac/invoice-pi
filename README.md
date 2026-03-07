# Invoice Downloader (Pi4 / Docker / Playwright API)

API-Container für den automatisierten Rechnungsdownload **Freenet** & **NetAachen**.
- Raspberry Pi 4 (64-bit) kompatibel
- Playwright (Chromium, headless)
- FastAPI: `POST /download` mit `{ "site": "freenet" | "netaachen" }`
- Downloads unter `./downloads` (Volume)

## Schnellstart

```bash
cp .env.sample .env
# .env bearbeiten (Credentials setzen)

docker compose up --build

# Test
curl -s -X POST http://localhost:8080/download       -H "Content-Type: application/json"       -d '{"site":"freenet"}' | jq

curl -s -X POST http://localhost:8080/download       -H "Content-Type: application/json"       -d '{"site":"netaachen"}' | jq
```

## Umgebungsvariablen
Siehe `.env.sample`. Wichtige Flags:
- `HEADLESS=true|false` – für Debug (false = Browser sichtbar, nur lokal sinnvoll)
- `LOG_LEVEL=DEBUG|INFO|...`

## Ordner
- `downloads/` – Zielverzeichnis für PDF-Dateien (gemountet)
- `pwdata/` – persistente Browserprofile für Sessions/Cookies

## Security
- **.env nicht committen**.
- Optional: Docker Secrets verwenden.
