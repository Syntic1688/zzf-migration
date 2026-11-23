"""Schritt 3 der Migrationspipeline: Laden über die Schnittstelle JSON-2.

Lädt die Tabellen aus importdateien.tabellen() der Reihe nach mit der Methode load, die auch der
Import über die Oberfläche nutzt. Odoo übernimmt eine Tabelle ganz oder gar nicht: Meldet es
bei einer Zeile einen Fehler, bricht der Lauf ab und nichts aus dieser Tabelle wird gespeichert.
Über die externen Kennungen ändert ein wiederholter Lauf die vorhandenen Datensätze, statt sie
doppelt anzulegen.

Aufruf: ODOO_URL=… ODOO_DB=… ODOO_KEY=… python3 -I laden.py <Ordner mit den umgewandelten Daten>
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importdateien import tabellen  # noqa: E402
from odoo_api import Odoo, OdooFehler  # noqa: E402


def hauptversion(odoo):
    base = odoo("ir.module.module", "search_read", domain=[["name", "=", "base"]], fields=["latest_version"])
    return int(base[0]["latest_version"].split(".")[0])


def laden(quelle, odoo):
    version = hauptversion(odoo)
    bericht = {"odoo_version": version, "tabellen": {}}
    for datei, modell, sprache, felder, zeilen in tabellen(quelle, unternehmen_kennzeichnen=version < 20):
        if not zeilen:
            continue
        daten = [["" if wert is None else str(wert) for wert in zeile] for zeile in zeilen]
        beginn = time.monotonic()
        ergebnis = odoo(modell, "load", fields=felder, data=daten,
                        context={"lang": sprache, "tz": "Europe/Vienna", "tracking_disable": True})
        dauer = round(time.monotonic() - beginn, 2)
        fehler = [m for m in ergebnis.get("messages", []) if m.get("type") == "error"]
        if fehler or not ergebnis.get("ids"):
            beispiele = "; ".join(f"Zeile {m.get('rows', {}).get('from', '?')}: {m.get('message')}" for m in fehler[:5])
            raise OdooFehler(f"{datei} ({modell}) nicht geladen: {len(fehler)} Fehler. {beispiele}")
        if len(ergebnis["ids"]) != len(zeilen):
            raise OdooFehler(f"{datei}: {len(zeilen)} Zeilen, aber {len(ergebnis['ids'])} Datensätze")
        bericht["tabellen"][datei] = {"modell": modell, "datensaetze": len(ergebnis["ids"]),
                                      "warnungen": len(ergebnis.get("messages", [])), "sekunden": dauer}
    return bericht


if __name__ == "__main__":
    print(json.dumps(laden(sys.argv[1], Odoo()), ensure_ascii=False, indent=1))
