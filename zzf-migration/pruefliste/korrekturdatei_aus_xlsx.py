"""Macht aus der ausgefüllten Prüfliste (Excel) die Korrekturdatei der Pipeline.

Aufruf: python3 -I korrekturdatei_aus_xlsx.py <ausgefüllt.xlsx> <zuordnung.json> <pruefliste.csv> <Ausgabe.csv>
        [--ok-ohne-vorschlag offen|vorlaeufig]

„ok“ übernimmt den Vorschlag der Zeile samt Zusatzkorrekturen. „ok“ in einer Zeile ohne Vorschlag ist nicht
eindeutig: Mit „offen“ bleibt der Fall offen, mit „vorlaeufig“ gilt der vorläufige Wert als bestätigt.
"""
import argparse
import csv
import json
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook

ap = argparse.ArgumentParser()
ap.add_argument("xlsx")
ap.add_argument("zuordnung")
ap.add_argument("pruefliste")
ap.add_argument("ausgabe")
ap.add_argument("--ok-ohne-vorschlag", choices=["offen", "vorlaeufig"], default="offen")
a = ap.parse_args()

zuordnung = json.load(open(a.zuordnung, encoding="utf-8"))
vorlaeufig = {r["Nr"]: r["Vorläufig"] for r in csv.DictReader(open(a.pruefliste, encoding="utf-8-sig"))}
wb = load_workbook(a.xlsx, data_only=True)

eintraege = []
for blatt, spalte_e, spalte_b in (("Schnelle Fälle", 10, 11), ("Gewichte", 9, 10)):
    ws = wb[blatt]
    for z in range(5, ws.max_row + 1):
        nr = ws.cell(z, 1).value
        if nr is None:
            continue
        eintraege.append((str(int(nr)), ws.cell(z, spalte_e).value, ws.cell(z, spalte_b).value))

zeilen, offen, unklar, bemerkungen = [], [], [], []
for nr, wert, bemerkung in sorted(eintraege, key=lambda e: int(e[0])):
    z = zuordnung[nr]
    if bemerkung:
        bemerkungen.append((nr, bemerkung))
    if wert is None or str(wert).strip() == "":
        offen.append(nr)
        continue
    text = str(wert).strip()
    if text.lower() == "ok":
        if z["vorschlag"]:
            entscheidung = z["vorschlag"]
            zusatz = z["dazu_bei_ok"]
        elif a.ok_ohne_vorschlag == "vorlaeufig":
            entscheidung = vorlaeufig[nr] or ("0" if z["feld"] in ("Gewicht", "Verkaufspreis") else "")
            zusatz = []
            if entscheidung == "":
                unklar.append((nr, "ok ohne Vorschlag und ohne vorläufigen Wert"))
                continue
        else:
            unklar.append((nr, "ok ohne Vorschlag"))
            continue
    else:
        entscheidung, zusatz = text, []
        if z["feld"] == "Land":
            entscheidung = text.upper()
        elif z["feld"] in ("Gewicht", "Verkaufspreis"):
            try:
                entscheidung = str(Decimal(text.replace(",", ".")))
            except InvalidOperation:
                unklar.append((nr, f"keine Zahl: {text!r}"))
                continue
        elif isinstance(wert, float):
            entscheidung = str(Decimal(str(wert)))
    zeilen.append([z["bereich"], z["nummer"], z["feld"], entscheidung])
    for b, n, f, w in zusatz:
        zeilen.append([b, n, f, w])

with open(a.ausgabe, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Bereich", "Nummer", "Feld", "Entscheidung"])
    w.writerows(zeilen)

print(json.dumps({"faelle": len(eintraege), "entschieden": len(eintraege) - len(offen) - len(unklar),
                  "korrekturzeilen": len(zeilen), "offen_leer": offen, "unklar": unklar,
                  "bemerkungen": len(bemerkungen)}, ensure_ascii=False))
