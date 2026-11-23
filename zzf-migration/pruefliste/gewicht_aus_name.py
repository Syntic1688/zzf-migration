"""Vorschlag für das Gewicht je Einheit (kg) aus Bezeichnung und Einheit eines Artikels.

Nur ein Vorschlag für die Prüfliste; entscheiden muss die Geschäftsführung.
Liter zählen wie im Altsystem 1 : 1 als Kilogramm."""
import re
from decimal import Decimal

Z = r"(\d+(?:[.,]\d+)?)"
E = r"(kg|g|l)\b"


def _d(s):
    return Decimal(s.replace(",", "."))


def _kg(wert, einheit):
    return _d(wert) / (1000 if einheit.lower() == "g" else 1)


MEHRFACH = [
    (re.compile(rf"(?<![\d.,])(\d+)\s*[x×]\s*{Z}\s*{E}", re.I), (1, 2, 3)),     # 20x102g, 2x8L
    (re.compile(rf"{Z}\s*(kg|g|l)\s*[x×]\s*(\d+)", re.I), (3, 1, 2)),          # 1kgx10pa, 18gx20pa
    (re.compile(rf"{Z}\s*{E}\s*/\s*(\d+)\s*(?:pa|do|st|fl)", re.I), (3, 1, 2)), # 75g/30pa/Kt
]
EINZELN = re.compile(rf"{Z}\s*{E}", re.I)                                       # 500g, 25kg/Sa, 1,8L/fl
KARTON_FOLGT = re.compile(r"\s*/\s*(kt|knt)\b", re.I)


def vorschlag(name, einheit):
    """Gibt (Gewicht in kg, Begründung) zurück oder (None, None)."""
    name = name or ""
    if einheit == "Kilogramm":
        return Decimal("1.000"), "Einheit ist Kilogramm"
    for muster, (ia, iw, ie) in MEHRFACH:
        m = muster.search(name)
        if m:
            wert = int(m.group(ia)) * _kg(m.group(iw), m.group(ie))
            return wert.quantize(Decimal("0.001")), _begruendung(m)
    m = EINZELN.search(name)
    if m and (einheit != "Karton" or KARTON_FOLGT.match(name, m.end())):
        return _kg(m.group(1), m.group(2)).quantize(Decimal("0.001")), _begruendung(m)
    return None, None


def _begruendung(m):
    text = f"aus der Bezeichnung: {m.group(0).strip()}"
    if re.search(r"\d\s*l\b", m.group(0), re.I):
        text += " (1 Liter = 1 kg wie im Altsystem)"
    return text
