import re
import pdfplumber
from datetime import datetime
from pathlib import Path


# ── Datum-Normalisierung ──────────────────────────────────────────────────────

def _normalize_date(raw: str) -> str | None:
    """Versucht verschiedene Datumsformate zu normalisieren → YYYY-MM-DD."""
    raw = raw.strip()
    formats = [
        "%d.%m.%Y", "%d.%m.%y",
        "%d/%m/%Y", "%d/%m/%y",
        "%Y-%m-%d",
        "%d. %B %Y", "%d. %b %Y",
        "%B %d, %Y", "%b %d, %Y",
    ]
    # Monatsnamen DE→EN
    de_months = {
        "Januar": "January", "Februar": "February", "März": "March",
        "April": "April", "Mai": "May", "Juni": "June",
        "Juli": "July", "August": "August", "September": "September",
        "Oktober": "October", "November": "November", "Dezember": "December",
        "Jan": "Jan", "Feb": "Feb", "Mär": "Mar", "Apr": "Apr",
        "Jun": "Jun", "Jul": "Jul", "Aug": "Aug", "Sep": "Sep",
        "Okt": "Oct", "Nov": "Nov", "Dez": "Dec",
    }
    normalized = raw
    for de, en in de_months.items():
        normalized = normalized.replace(de, en)
    for fmt in formats:
        try:
            return datetime.strptime(normalized, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ── Regex-Pattern ─────────────────────────────────────────────────────────────

# Primäre Datumsmuster (Rechnungsdatum bevorzugt)
DATE_PATTERNS = [
    r"Rechnungsdatum[:\s]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    r"Datum[:\s]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    r"Invoice Date[:\s]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    r"Date[:\s]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    r"(\d{1,2}\.\s*(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s*\d{4})",
    r"(\d{1,2}\.\d{2}\.\d{4})",
]

# Fallback-Datumsmuster wenn Rechnungsdatum nicht gefunden (z.B. Amazon Lieferdatum)
DATE_FALLBACK_PATTERNS = [
    r"Lieferdatum[:\s/]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    r"/Lieferdatum[:\s]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    r"Delivery Date[:\s]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    r"Leistungsdatum[:\s/]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
]

INVOICE_NR_PATTERNS = [
    r"Rechnungsnummer[:\s#]+([A-Z0-9\-\/]{4,30})",
    r"Rechnungs-?Nr\.?[:\s#]+([A-Z0-9\-\/]{4,30})",
    r"Invoice\s*(?:No|Number|Nr)\.?[:\s#]+([A-Z0-9\-\/]{4,30})",
    r"Beleg(?:nummer)?[:\s#]+([A-Z0-9\-\/]{4,30})",
    r"(?:No|Nr)\.[:\s]+([A-Z0-9\-\/]{4,30})",
    # Amazon-spezifisch
    r"Bestellnummer[:\s]+(\d{3}-\d{7}-\d{7})",
    r"Order\s*(?:ID|No)[:\s]+(\d{3}-\d{7}-\d{7})",
    # Freenet/NetAachen
    r"Rechnungs-ID[:\s]+([A-Z0-9\-]{4,20})",
]

# Bekannte Lieferanten — Reihenfolge wichtig (spezifischer zuerst)
SUPPLIER_PATTERNS = [
    (r"Amazon Business", "Amazon Business EU SARL"),
    (r"Amazon\.de|amazon\.de", "Amazon"),
    (r"Microsoft Ireland|Microsoft Deutschland", "Microsoft"),
    (r"freenet|Freenet", "Freenet"),
    (r"NetAachen|net aachen", "NetAachen"),
    (r"Tesla", "Tesla"),
    (r"Haufe", "Haufe"),
    (r"Google", "Google"),
    (r"Apple", "Apple"),
    (r"Telekom|Deutsche Telekom", "Telekom"),
    (r"Vodafone", "Vodafone"),
    (r"1&1|1und1", "1und1"),
    (r"DATEV", "DATEV"),
    (r"Lexware", "Lexware"),
]


def _extract_text(pdf_path: str) -> str:
    """Extrahiert Text aus allen Seiten eines PDFs."""
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return "\n".join(text_parts)


def _find_date(text: str) -> str | None:
    for pattern in DATE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            normalized = _normalize_date(m.group(1))
            if normalized:
                return normalized
    # Fallback: Liefer- oder Leistungsdatum
    for pattern in DATE_FALLBACK_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            normalized = _normalize_date(m.group(1))
            if normalized:
                return normalized
    return None


def _find_invoice_number(text: str) -> str | None:
    for pattern in INVOICE_NR_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _find_supplier(text: str, filename: str = "") -> str | None:
    combined = text + " " + filename
    for pattern, name in SUPPLIER_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return name
    # Fallback: erste Zeile des PDFs oft der Firmenname
    first_lines = text.strip().splitlines()[:5]
    for line in first_lines:
        line = line.strip()
        if len(line) > 3 and len(line) < 60 and not re.match(r"^\d", line):
            return line
    return None


def _safe_filename(s: str) -> str:
    """Entfernt ungültige Zeichen für Dateinamen."""
    s = re.sub(r'[<>:"/\\|?*\s]', '_', s)
    s = re.sub(r'_+', '_', s)
    return s.strip('_')


def analyze_invoice(pdf_path: str) -> dict:
    """
    Analysiert ein PDF und extrahiert Rechnungsdatum, Lieferant und Rechnungsnummer.
    Gibt auch einen Vorschlags-Dateinamen zurück.
    """
    if not Path(pdf_path).is_file():
        raise FileNotFoundError(f"Datei nicht gefunden: {pdf_path}")

    filename = Path(pdf_path).stem
    text = ""

    try:
        text = _extract_text(pdf_path)
    except Exception as e:
        return {
            "error": f"PDF konnte nicht gelesen werden: {e}",
            "invoice_date": None,
            "supplier": None,
            "invoice_number": None,
            "suggested_filename": None,
            "raw_text_preview": None,
        }

    invoice_date   = _find_date(text)
    supplier       = _find_supplier(text, filename)
    invoice_number = _find_invoice_number(text)

    # Vorschlags-Dateiname — Supplier 1:1, nur wirklich ungültige Zeichen entfernen
    def _safe_part(s: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', '', s).strip()

    date_part    = invoice_date or "DATUM-UNBEKANNT"
    supplier_part = _safe_part(supplier) if supplier else "LIEFERANT-UNBEKANNT"
    number_part  = _safe_part(invoice_number) if invoice_number else "NR-UNBEKANNT"
    suggested_filename = f"{date_part}_{supplier_part}_{number_part}.pdf"

    return {
        "invoice_date":        invoice_date,
        "supplier":            supplier,
        "invoice_number":      invoice_number,
        "suggested_filename":  suggested_filename,
        "raw_text_preview":    text[:500] if text else None,
    }


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 2:
        print("Usage: python3 analyze.py <pdf-path>")
        sys.exit(1)
    result = analyze_invoice(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
