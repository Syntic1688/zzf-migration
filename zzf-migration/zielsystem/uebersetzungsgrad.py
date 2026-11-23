"""Übersetzungsgrad der Oberflächentexte in Odoo 19 und ERPNext 16 (Chinesisch, Deutsch).

Zählt je Modul (Verkauf, Lager, Einkauf, Buchhaltung), wie viele Oberflächentexte der
Sprachdatei (.po) übersetzt sind. Grundlage: Quellcode von GitHub
(Odoo 19.0 und ERPNext Branch version-16). Aufruf:
    python3 uebersetzungsgrad.py <odoo-verzeichnis> <erpnext-verzeichnis>
"""
import sys
import polib

def anteil(eintraege):
    eintraege = [e for e in eintraege if not e.obsolete]
    uebersetzt = [e for e in eintraege if e.translated()]
    return len(uebersetzt), len(eintraege)

odoo, erpnext = sys.argv[1], sys.argv[2]
module_odoo = {"Verkauf": "sale", "Lager": "stock", "Einkauf": "purchase", "Buchhaltung": "account"}
module_erpnext = {"Verkauf": "erpnext/selling/", "Lager": "erpnext/stock/",
                  "Einkauf": "erpnext/buying/", "Buchhaltung": "erpnext/accounts/"}

print("System;Sprache;Modul;übersetzt;gesamt;Anteil")
for sprache_odoo, sprache_erp, name in (("zh_CN", "zh", "Chinesisch"), ("de", "de", "Deutsch")):
    for modul, ordner in module_odoo.items():
        u, g = anteil(polib.pofile(f"{odoo}/addons/{ordner}/i18n/{sprache_odoo}.po"))
        print(f"Odoo 19;{name};{modul};{u};{g};{u/g:.1%}")
    po = polib.pofile(f"{erpnext}/erpnext/locale/{sprache_erp}.po")
    for modul, praefix in module_erpnext.items():
        auswahl = [e for e in po if any(o[0].startswith(praefix) for o in e.occurrences)]
        u, g = anteil(auswahl)
        print(f"ERPNext 16;{name};{modul};{u};{g};{u/g:.1%}")
