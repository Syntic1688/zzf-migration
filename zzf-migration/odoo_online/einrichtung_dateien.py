"""Importdateien 12 und 13 für Odoo Online: Lieferscheinvorlage (Ansicht vom Typ QWeb) und Bericht.

In Odoo 20 zeigt das Formular der Ansichten das Feld „Schlüssel“ nicht mehr; Odoo vergibt dann
einen zufälligen Schlüssel, und der Bericht findet die Vorlage nicht unter zzf.lieferschein. Über
den Import lassen sich Schlüssel und Druckmenü (binding_model_id) direkt setzen.

Aufruf: python3 -I einrichtung_dateien.py <pipeline/lieferschein.xml> <Zielordner>
"""
import csv
import os
import sys


def main(vorlage, ziel):
    arch = open(vorlage, encoding="utf-8").read().strip()
    dateien = {
        "12_lieferschein_vorlage.csv": (["id", "name", "type", "key", "arch_db"],
                                        [["zzf_lieferschein_vorlage", "zzf.lieferschein", "qweb", "zzf.lieferschein",
                                          arch]]),
        "13_lieferschein_bericht.csv": (["id", "name", "model", "report_type", "report_name", "binding_model_id/id",
                                         "binding_type", "print_report_name"],
                                        [["zzf_lieferschein_bericht", "Lieferschein ZZF", "stock.picking", "qweb-pdf",
                                          "zzf.lieferschein", "stock.model_stock_picking", "report",
                                          "'Lieferschein - %s' % object.name"]]),
    }
    os.makedirs(ziel, exist_ok=True)
    for name, (kopf, zeilen) in dateien.items():
        with open(os.path.join(ziel, name), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(kopf)
            w.writerows(zeilen)
    return list(dateien)


if __name__ == "__main__":
    print(main(sys.argv[1], sys.argv[2]))
