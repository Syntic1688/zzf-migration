"""Export der acht Datentabellen des Altsystems als CSV-Dateien (UTF-8).

Aufruf: python3 -I export_csv.py <Ordner HM9 der Kopie> <Zielordner>

Je Tabelle entsteht eine CSV-Datei; die Monatsdateien einer Belegart werden in zeitlicher
Reihenfolge zu einer Datei zusammengeführt. Die Kopie wird nur gelesen.

Umwandlung je Datentyp (Kennbuchstabe im Dateikopf):
- C (Text):    Bytes mit dem Decoder aus pipeline/dbf.py in Unicode lesen, Füllleerzeichen am Ende entfernen,
               halbes chinesisches Zeichen am Textende entfernen (wird gezählt)
- N (Zahl):    Text ohne Leerzeichen übernehmen, Punkt als Dezimalzeichen, Nachkommastellen wie im
               Original (z. B. 27.90); nur Leerzeichen -> leeres Feld
- D (Datum):   JJJJMMTT -> JJJJ-MM-TT (ISO 8601); nur Leerzeichen -> leeres Feld
- L (Ja/Nein): T/Y -> true, F/N -> false; Leerzeichen oder ? -> leeres Feld

Jede Zeile erhält zusätzlich _datei (Name der Quelldatei), _satz (Satznummer in der Quelldatei,
ab 1) und _geloescht (Löschkennzeichen des Altsystems), damit jeder Wert auf seinen
Ursprung zurückgeführt werden kann.

Format: UTF-8 ohne BOM, Komma als Trennzeichen, Anführungszeichen nur bei Bedarf (RFC 4180).
"""
import collections
import csv
import datetime
import decimal
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline"))
from dbf import Tabelle, dekodiere  # noqa: E402

TABELLEN = {
    "KUNDEN": ["KUNDEN.DBF"],
    "WAREN": ["WAREN.DBF"],
    "LIEFER": ["LIEFER.DBF"],
    "FIFO": ["FIFO.DBF"],
    "LH": ["LIF/LH*.DBF"],
    "LD": ["LIF/LD*.DBF"],
    "EH": ["EIN/EH*.DBF"],
    "ED": ["EIN/ED*.DBF"],
}


def wert(typ, nk, raw, zaehler):
    if typ == "C":
        text, halb = dekodiere(raw)
        if halb:
            zaehler["halbe_zeichen_entfernt"] += 1
        return text
    s = raw.decode("ascii").strip()
    if typ == "N":
        if not s:
            return ""
        decimal.Decimal(s)  # löst einen Fehler aus, wenn der Text keine Zahl ist
        return s
    if typ == "D":
        if not s:
            return ""
        return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8])).isoformat()
    if typ == "L":
        if s in ("T", "t", "Y", "y"):
            return "true"
        if s in ("F", "f", "N", "n"):
            return "false"
        return ""
    raise ValueError(f"unbekannter Datentyp {typ}")


def main(quelle, ziel):
    os.makedirs(ziel, exist_ok=True)
    bericht = {}
    for name, muster in TABELLEN.items():
        dateien = []
        for m in muster:
            dateien.extend(sorted(glob.glob(os.path.join(quelle, m))))
        zaehler = collections.Counter()
        felder = None
        with open(os.path.join(ziel, f"{name}.csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            for pfad in dateien:
                t = Tabelle(pfad)
                if felder is None:
                    felder = t.felder
                    w.writerow([fn for fn, _, _, _ in felder] + ["_datei", "_satz", "_geloescht"])
                elif [x[:2] for x in t.felder] != [x[:2] for x in felder]:
                    raise ValueError(f"{pfad}: Spalten weichen von der ersten Monatsdatei ab")
                for nr, (geloescht, werte) in enumerate(t.roh(), start=1):
                    zeile = [wert(typ, nk, werte[fn], zaehler) for fn, typ, _, nk in t.felder]
                    w.writerow(zeile + [os.path.basename(pfad), nr, "true" if geloescht else "false"])
                    zaehler["zeilen"] += 1
                    zaehler["geloescht"] += geloescht
        typen = collections.Counter(typ for _, typ, _, _ in felder)
        bericht[name] = {"dateien": len(dateien), "spalten": len(felder), "datentypen": dict(typen), **zaehler}
    bericht["zeilen_gesamt"] = sum(v["zeilen"] for v in bericht.values() if isinstance(v, dict))
    print(json.dumps(bericht, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
