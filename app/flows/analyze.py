import re
import pdfplumber
from datetime import datetime
from pathlib import Path

# ── Datum-Normalisierung ──────────────────────────────────────────────────────

def _ocr_text(pdf_path: str) -> str:
    """OCR-Fallback für gescannte PDFs ohne extrahierbaren Text."""
    try:
        from pdf2image import convert_from_path
        import pytesseract
        images = convert_from_path(pdf_path, dpi=200)
        parts = []
        for img in images[:3]:  # max 3 Seiten
            text = pytesseract.image_to_string(img, lang="deu+eng")
            if text.strip():
                parts.append(text)
        return "\n".join(parts)
    except Exception as e:
        print(f"⚠️ OCR Fehler: {e}")
        return ""

def _fix_microsoft_date(date_str: str) -> str:
    """Korrigiert Microsoft YYYY-DD-MM Datumsformat."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_str)
    if m:
        y, a, b = m.group(1), int(m.group(2)), int(m.group(3))
        if a > 12 and b <= 12:
            return f"{y}-{b:02d}-{a:02d}"
        if b <= 6 < a:
            return f"{y}-{b:02d}-{a:02d}"
    return date_str

def _normalize_date(raw: str) -> str | None:
    """Versucht verschiedene Datumsformate zu normalisieren → YYYY‑MM‑DD."""
    raw = raw.strip()

    formats = [
        "%d.%m.%Y", "%d.%m.%y",
        "%d/%m/%Y", "%d/%m/%y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%b-%Y", "%d-%b-%y",
        "%d-%B-%Y", "%d-%B-%y",
        "%d. %B %Y", "%d. %b %Y",
        "%d %B %Y", "%d %b %Y",
        "%B %d, %Y", "%b %d, %Y",
    ]

    # Monatsnamen DE → EN
    de_months = {
        "Januar": "January", "Februar": "February", "März": "March",
        "April": "April", "Mai": "May", "Juni": "June",
        "Juli": "July", "August": "August", "September": "September",
        "Oktober": "October", "November": "November", "Dezember": "December",

        "Jan": "Jan", "Feb": "Feb", "Mär": "Mar", "Apr": "Apr",
        "Jun": "Jun", "Jul": "Jul", "Aug": "Aug", "Sep": "Sep",
        "Okt": "Oct", "Nov": "Nov", "Dez": "Dec",

        "Jan.": "Jan", "Feb.": "Feb", "Mär.": "Mar", "Apr.": "Apr",
        "Jun.": "Jun", "Jul.": "Jul", "Aug.": "Aug", "Sep.": "Sep",
        "Okt.": "Oct", "Nov.": "Nov", "Dez.": "Dec",
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

# ✅ DEFEKTES DATUMSREGEX ERSETZT DURCH ROBUSTE VERSION
DATE_PATTERNS = [
    r"Belegdatum[:\s]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    r"Rechnungsdatum[:\s]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    r"Rechnungsdatum[:\s]+(\d{4}[-/]\d{2}[-/]\d{2})",
    r"Rechnungsdatum[:\s]+(\d{1,2}-[A-Za-z]{3,9}-\d{4})",
    r"Datum[:\s]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    r"Invoice Date[:\s]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    r"Date[:\s]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",

    # ✅ robustes deutsches Datum: 30. Dez. 2024 / 6. Januar 2025
    r"(\d{1,2}\.\s*(?:Jan\.?|Feb\.?|Mär\.?|Apr\.?|Mai|Jun\.?|Jul\.?|"
    r"Aug\.?|Sep\.?|Okt\.?|Nov\.?|Dez\.?|"
    r"Januar|Februar|März|April|Mai|Juni|Juli|August|September|"
    r"Oktober|November|Dezember)\s*\d{4})",

    r"(\d{1,2}\.\d{2}\.\d{4})",
]
# Fallback-Datumsmuster
DATE_FALLBACK_PATTERNS = [
    r"Lieferdatum[:\s/]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    r"Lieferdatum[:\s/]+(\d{1,2}\s+\w+\s+\d{4})",
    r"/Lieferdatum[:\s]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    r"/Lieferdatum[:\s]+(\d{1,2}\s+\w+\s+\d{4})",
    r"Delivery Date[:\s]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    r"Leistungsdatum[:\s/]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
]

INVOICE_NR_PATTERNS = [
    r"Rechnungsnummer[:\s#]+([A-Z0-9\-/]{4,30})",
    r"Rechnungs-?Nr\.?[:\s#]+([A-Z0-9\-/]{4,30})",
    r"Rechnung\s*-?\s*Nr\.?\s*:?\s*([0-9][0-9\s\-/]{1,15}[0-9])",
    r"Invoice\s*(?:No|Number|Nr)\.?[:\s#]+([A-Z0-9\-/]{4,30})",
    r"Beleg(?:nummer)?[:\s#]+([A-Z0-9\-/]{4,30})",
    r"(?:No|Nr)\.[:\s]+([A-Z0-9\-/]{4,30})",

    # Amazon
    r"Bestellnummer[:\s]+(\d{3}-\d{7}-\d{7})",
    r"Order\s*(?:ID|No)[:\s]+(\d{3}-\d{7}-\d{7})",

    # Microsoft
    r"Abrechnungsnummer\s+([A-Z0-9\-]{4,20})",

    # Freenet/NetAachen
    r"Rechnungs-ID[:\s]+([A-Z0-9\-]{4,20})",

    # Pieksauber
    r"(RECH\d{8})",
]

AMOUNT_PATTERNS = [
    (r"(?:^|\n)TOTAL\s*\n\s*([\d.,]+)", 1),
    (r"Total\s+EUR\s+([\d.,]+)", 1),
    (r"Gesamtbetrag\s+EUR\s+([\d.,]+)", 1),

    (r"Gesamtsumme\s+EUR\s+([\d.,]+)", 1),

    (r"Zahlbetrag\s+([\d.,]+\s*€)", 1),

    (r"Rechnungsbetrag\s+gesamt\s+([\d.,]+\s*€)", 1),

    (r"Fälligkeitsdatum:[^\n]+\n([\d.,]+\s*EUR)", 1),

    (r"Gebühren:\s*([\d.,]+)", 1),

    (r"Gesamtbetrag\s*\(EUR\)\s*([\d.,]+)", 1),
    (r"Gesamtbetrag\s+([\d.,]+\s*(?:EUR|Euro|€))", 1),
    (r"([\d.,]+)\s*Euro(?!\w)", 1),
    (r"Brutto[:\s]+([\d.,]+\s*(?:EUR|€))", 1),
    (r"Summe[:\s]+([\d.,]+\s*(?:EUR|€))", 1),
    (r"Total[:\s]+([\d.,]+\s*(?:EUR|€))", 1),
    (r"Rechnungsbetrag[:\s]+([\d.,]+\s*(?:EUR|€|Euro))", 1),
    (r"Gesamtbetrag inkl[^\n]*?([\d.,]+\s*(?:EUR|€))", 1),
    (r"([\d.,]+)\s*EUR(?!\w)(?!\d)", 1),
]

SUPPLIER_PATTERNS = [
    (r"Pieksauber|PPiieekkssaauubbeerr|pieksauber", "Pieksauber"),
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

def _deduplicate_line(line: str) -> str:
    """Entfernt OCR-Zeichenverdopplungen."""
    if len(line) < 4:
        return line

    pairs = sum(1 for i in range(0, len(line) - 1, 2) if line[i] == line[i+1])
    ratio = pairs / max(len(line) / 2, 1)

    if ratio < 0.5:
        return line

    result = []
    i = 0
    while i < len(line):
        result.append(line[i])
        if i + 1 < len(line) and line[i] == line[i+1]:
            i += 2
        else:
            i += 1

    return "".join(result)

def _deduplicate_chars(text: str) -> str:
    return "\n".join(_deduplicate_line(line) for line in text.splitlines())

def _extract_text(pdf_path: str) -> str:
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)

    text = "\n".join(text_parts)
    text = _deduplicate_chars(text)

    if len(text.strip()) < 50:
        print("🔍 Wenig Text gefunden — versuche OCR...")
        ocr = _ocr_text(pdf_path)
        if len(ocr.strip()) > len(text.strip()):
            print(f"✅ OCR erfolgreich: {len(ocr)} Zeichen")
            text = _deduplicate_chars(ocr)
        else:
            print("⚠️ OCR lieferte auch wenig Text")

    return text
def _find_date(text: str) -> str | None:

    # Zeilenumbrüche glätten
    normalized_text = text.replace("\n/", "/")
    normalized_text = re.sub(r"(\w)\n(\d)", r"\1 \2", normalized_text)

    # Leerzeichen innerhalb ISO-Daten entfernen
    normalized_text = re.sub(r"(\d)\s*[-–]\s*(\d{2})\s*[-–]\s*(\d{2})",
                             r"\1-\2-\3",
                             normalized_text)

    # Hauptmuster
    for pattern in DATE_PATTERNS:
        m = re.search(pattern, normalized_text, re.IGNORECASE)
        if m:
            normalized = _normalize_date(m.group(1))
            if normalized:
                return _fix_microsoft_date(normalized)

    # Fallback
    for pattern in DATE_FALLBACK_PATTERNS:
        m = re.search(pattern, normalized_text, re.IGNORECASE)
        if m:
            normalized = _normalize_date(m.group(1))
            if normalized:
                return normalized

    # Notlösung
    for pattern in [
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{1,2}\.\d{2}\.\d{4})",

        # deutsche ausgeschriebene Monate (robust)
        r"(\d{1,2}\.\s*(?:Jan\.?|Feb\.?|Mär\.?|Apr\.?|Mai|Jun\.?|Jul\.?|"
        r"Aug\.?|Sep\.?|Okt\.?|Nov\.?|Dez\.?|"
        r"Januar|Februar|März|April|Mai|Juni|Juli|August|September|"
        r"Oktober|November|Dezember)\s*\d{4})",

        r"(\d{1,2}\s+(?:Jan|Feb|Mär|Apr|Mai|Jun|Jul|Aug|Sep|Okt|Nov|Dez)\.?\s+\d{4})",
        r"(\d{1,2}\s+(?:Januar|Februar|März|April|Mai|Juni|Juli|August|"
        r"September|Oktober|November|Dezember)\s+\d{4})",
    ]:
        m = re.search(pattern, normalized_text, re.IGNORECASE)
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


def _normalize_amount(val: str) -> str:
    val = val.strip()
    val = re.sub(r"EUR\s*", "", val).strip()

    # Amerikanisch 1,234.56
    if re.match(r"^[\d,]+\.\d{2}$", val):
        val = val.replace(",", "").replace(".", ",")

    elif re.match(r"^\d+\.\d{1,2}$", val):
        val = val.replace(".", ",")

    if not val.endswith("€"):
        val += " €"

    return val


def _find_amount(text: str) -> str | None:
    for pattern, group in AMOUNT_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            val = m.group(group).strip()
            return _normalize_amount(val)
    return None


def _find_supplier(text: str, filename: str = "") -> str | None:
    combined = text + " " + filename

    for pattern, name in SUPPLIER_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return name

    # Fallback: erste sinnvolle Zeile
    for line in text.strip().splitlines()[:10]:
        line = re.sub(r"^[^\w]+", "", line).strip()
        if 3 < len(line) < 60 and not re.match(r"^\d", line):
            return line

    return None


def _safe_filename(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\s]', "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


def analyze_invoice(pdf_path: str) -> dict:

    if not Path(pdf_path).is_file():
        raise FileNotFoundError(f"Datei nicht gefunden: {pdf_path}")

    filename = Path(pdf_path).stem

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

    invoice_date = _find_date(text)
    supplier = _find_supplier(text, filename)
    invoice_number = _find_invoice_number(text)
    amount = _find_amount(text)

    # ✅ PIEKSAUBER: frühestes Datum erzwingen
    if supplier == "Pieksauber":
        german = re.findall(
            r'(\d{1,2}\.\s*(?:Jan\.?|Feb\.?|Mär\.?|Apr\.?|Mai|Jun\.?|Jul\.?|'
            r'Aug\.?|Sep\.?|Okt\.?|Nov\.?|Dez\.?|'
            r'Januar|Februar|März|April|Mai|Juni|Juli|August|September|'
            r'Oktober|November|Dezember)\s*\d{4})',
            text,
            flags=re.IGNORECASE
        )
        parsed = [_normalize_date(d) for d in german if _normalize_date(d)]
        if parsed:
            invoice_date = min(parsed)

    # Dateiname vorbereiten
    def _safe_part(s: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', "", s).strip()

    date_part = invoice_date or "DATUM-UNBEKANNT"
    supplier_part = _safe_part(supplier) if supplier else "LIEFERANT-UNBEKANNT"
    number_part = _safe_part(invoice_number) if invoice_number else "NR-UNBEKANNT"

    suggested_filename = f"{date_part}_{supplier_part}_{number_part}.pdf"

    return {
        "invoice_date": invoice_date,
        "supplier": supplier,
        "invoice_number": invoice_number,
        "amount": amount,
        "suggested_filename": suggested_filename,
        "raw_text_preview": text[:500] if text else None,
    }


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 2:
        print("Usage: python3 analyze.py <pdf-path>")
        sys.exit(1)

    result = analyze_invoice(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))