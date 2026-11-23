"""Schritt 4 der Migrationspipeline: Archiv.

Legt die Daten des Altsystems als CSV-Dateien in einem Archivordner ab: die Lieferscheine und
Wareneingänge mit ihren Positionen und zur Vollständigkeit auch die Stammtabellen und die
Lagerposten. Die Dateien lassen sich mit jeder Tabellenkalkulation öffnen, auch wenn das
Altsystem nicht mehr läuft. Eine Inhaltsdatei nennt je Datei die Herkunft, die Anzahl der
Datensätze und die Prüfsumme (SHA-256); mit ihr lässt sich später zeigen, dass das Archiv
unverändert ist.

Aufruf: python3 -I archiv.py <Zwischenspeicher> <Archivordner>
"""
import csv
import hashlib
import json
import os
import shutil
import sys

ARCHIV = [  # Datei im Zwischenspeicher, Name im Archiv, Herkunft im Altsystem
    ("LH.csv", "Lieferscheine.csv", "LIF/LH*.DBF"),
    ("LD.csv", "Lieferscheinpositionen.csv", "LIF/LD*.DBF"),
    ("EH.csv", "Wareneingaenge.csv", "EIN/EH*.DBF"),
    ("ED.csv", "Wareneingangspositionen.csv", "EIN/ED*.DBF"),
    ("KUNDEN.csv", "Kunden.csv", "KUNDEN.DBF"),
    ("WAREN.csv", "Artikel.csv", "WAREN.DBF"),
    ("LIEFER.csv", "Lieferanten.csv", "LIEFER.DBF"),
    ("FIFO.csv", "Lagerposten.csv", "FIFO.DBF"),
]


def sha256(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def archivieren(zwischen, archiv):
    os.makedirs(archiv, exist_ok=True)
    inhalt = []
    for quelle, ziel, herkunft in ARCHIV:
        shutil.copyfile(os.path.join(zwischen, quelle), os.path.join(archiv, ziel))
        with open(os.path.join(archiv, ziel), encoding="utf-8", newline="") as f:
            zeilen = sum(1 for _ in csv.reader(f)) - 1
        inhalt.append({"datei": ziel, "herkunft": herkunft, "datensaetze": zeilen,
                       "sha256": sha256(os.path.join(archiv, ziel))})
    with open(os.path.join(archiv, "inhalt.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["datei", "herkunft", "datensaetze", "sha256"])
        w.writeheader()
        w.writerows(inhalt)
    return inhalt


if __name__ == "__main__":
    print(json.dumps(archivieren(sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=1))
