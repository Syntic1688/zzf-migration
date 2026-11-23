"""Zuordnung zum Zielsystem in Tabellenform und Importdateien für die Oberfläche von Odoo.

tabellen() bildet aus den Ausgabedateien von umwandeln.py die Tabellen, die Odoo lädt: je
Tabelle das Modell, die Felder (technische Namen) und die Zeilen. Verweise nutzen externe
Kennungen (Felder mit /id). Ein zweiter Lauf ändert deshalb die vorhandenen Datensätze, statt
sie doppelt anzulegen. Dieselben Tabellen nutzt laden.py für das Laden über die Schnittstelle.

Als eigenes Programm aufgerufen, schreibt es die Tabellen als CSV-Dateien, die sich in Odoo
der Reihe nach über „Datensätze importieren“ laden lassen, etwa in einer eigenen Testdatenbank.
Die Dateien kommen ohne Felder aus, die sich zwischen Odoo 19 und Odoo 20 geändert haben.

Aufruf: python3 -I importdateien.py <Ordner mit den umgewandelten Daten> <Zielordner>
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import konfig  # noqa: E402

# Einheiten: vorhandene Einheiten von Odoo nutzen, die übrigen neu anlegen
EINHEIT_VORHANDEN = {"Stück": "uom.product_uom_unit", "Kilogramm": "uom.product_uom_kgm"}
# Steuern der österreichischen Lokalisierung (l10n_at) je Steuersatz: Verkauf, Einkauf
STEUERN = {20: ("20% Ust", "20% Vst"), 10: ("10% Ust R", "10% Vst")}
# Länder: Odoo führt jedes Land unter base.<Kürzel in Kleinbuchstaben>, das Vereinigte Königreich unter base.uk
LAND_AUSNAHMEN = {"GB": "base.uk"}
LAGER = "stock.stock_location_stock"


def land_kennung(kuerzel):
    """Externe Kennung des Landes in Odoo zu einem Länderkürzel wie AT, DE oder CN."""
    if not kuerzel:
        return None
    return LAND_AUSNAHMEN.get(kuerzel, "base." + kuerzel.lower())


def kurz(text):
    return text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")


def einheit_id(name):
    return EINHEIT_VORHANDEN.get(name) or "zzf_einheit_" + kurz(name)


def tabellen(quelle, unternehmen_kennzeichnen=False):
    """Liste von Tabellen in Ladereihenfolge: (Dateiname, Modell, Sprache, Felder, Zeilen).

    unternehmen_kennzeichnen: Kontakte als Unternehmen anlegen (Feld is_company). Nur bis
    Odoo 19 möglich; ab Odoo 20 bestimmt Odoo das selbst."""
    def lade(name):
        with open(os.path.join(quelle, name), encoding="utf-8") as f:
            return json.load(f)

    lieferanten, kunden = lade("lieferanten.json"), lade("kunden.json")
    artikel, preislisten = lade("artikel.json"), lade("preislisten.json")
    firma = ["is_company"] if unternehmen_kennzeichnen else []
    ja = ["True"] if unternehmen_kennzeichnen else []

    einheiten = sorted({a["uom"] for a in artikel} - set(EINHEIT_VORHANDEN))
    bereiche = [b for b in konfig.LAGERBEREICH.values() if any(a["location"] == b for a in artikel)]
    t = []
    t.append(("01_einheiten.csv", "uom.uom", "de_DE", ["id", "name"],
              [[einheit_id(e), e] for e in einheiten]))
    t.append(("02_produktkategorien.csv", "product.category", "de_DE", ["id", "name"],
              [["zzf_kategorie_" + kurz(b), b] for b in bereiche]))
    t.append(("03_lagerorte.csv", "stock.location", "de_DE", ["id", "name", "location_id/id"],
              [["zzf_lagerort_" + kurz(b), b, LAGER] for b in bereiche]))
    t.append(("04_einlagerungsregeln.csv", "stock.putaway.rule", "de_DE",
              ["id", "category_id/id", "location_in_id/id", "location_out_id/id"],
              [["zzf_einlagerung_" + kurz(b), "zzf_kategorie_" + kurz(b), LAGER, "zzf_lagerort_" + kurz(b)]
               for b in bereiche]))
    t.append(("05_preislisten.csv", "product.pricelist", "de_DE", ["id", "name", "sequence"],
              [[p["xid"], p["name"], i] for i, p in enumerate(preislisten, start=1)]))
    t.append(("06_lieferanten.csv", "res.partner", "de_DE",
              ["id", "name"] + firma + ["ref", "street", "zip", "city", "country_id/id", "phone", "customer_rank",
                                        "supplier_rank"],
              [[s["xid"], s["name"]] + ja + [s["ref"], s["street"], s["zip"], s["city"], land_kennung(s["country"]),
                                             s["phone"], 0, 1] for s in lieferanten]))
    t.append(("07_ansprechpartner.csv", "res.partner", "de_DE",
              ["id", "name", "parent_id/id", "type", "customer_rank", "supplier_rank"],
              [[s["xid"] + "_kontakt", s["ansprechpartner"], s["xid"], "contact", 0, 0]
               for s in lieferanten if s["ansprechpartner"]]))
    t.append(("08_kunden.csv", "res.partner", "de_DE",
              ["id", "name", "x_name_zh"] + firma + ["ref", "street", "street2", "zip", "city", "country_id/id",
                                                     "phone", "vat", "customer_rank", "supplier_rank",
                                                     "property_product_pricelist/id"],
              [[s["xid"], s["name"], s["x_name_zh"]] + ja + [s["ref"], s["street"], s["street2"], s["zip"], s["city"],
                                                            land_kennung(s["country"]), s["phone"], s["vat"], 1, 0,
                                                            s["pricelist"]] for s in kunden]))
    t.append(("09_produkte.csv", "product.template", "de_DE",
              ["id", "default_code", "name", "type", "is_storable", "uom_id/id", "categ_id/id", "taxes_id",
               "supplier_taxes_id", "list_price", "standard_price", "weight"],
              [[a["xid"], a["default_code"], a["name"], "consu", "True", einheit_id(a["uom"]),
                "zzf_kategorie_" + kurz(a["location"]) if a["location"] else None,
                STEUERN[a["steuer"]][0], STEUERN[a["steuer"]][1], a["list_price"], a["standard_price"], a["weight"]]
               for a in artikel]))
    t.append(("10_produkte_chinesisch.csv", "product.template", "zh_CN", ["id", "name"],
              [[a["xid"], a["name_zh"]] for a in artikel if a["name_zh"]]))
    t.append(("11_preislisteneintraege.csv", "product.pricelist.item", "de_DE",
              ["id", "pricelist_id/id", "product_tmpl_id/id", "compute_price", "fixed_price"],
              [[p["xid"] + "_" + e["artikel"][len("zzf_artikel_"):], p["xid"], e["artikel"], "fixed", e["fixed_price"]]
               for p in preislisten for e in p["eintraege"]]))
    return t


# In den Importdateien steht beim Zusatzfeld die Bezeichnung statt des technischen Namens. Odoo
# ordnet die Spalte so auch dann richtig zu, wenn das Feld mit Studio einen anderen Namen erhielt.
BEZEICHNUNG = {"x_name_zh": "Chinesischer Name"}


# Kommazahlen schreibt die Datei mit Dezimalkomma: Der Importdialog von Odoo stellt bei CSV-Dateien
# die Trennzeichen der Benutzersprache ein (Deutsch: Tausenderpunkt, Dezimalkomma). Aus 27.90 würde
# sonst 2790.
KOMMAZAHLEN = {"list_price", "standard_price", "weight", "fixed_price"}


def main(quelle, ziel):
    os.makedirs(ziel, exist_ok=True)
    anzahl = {}
    for datei, _modell, _sprache, felder, zeilen in tabellen(quelle):
        with open(os.path.join(ziel, datei), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow([BEZEICHNUNG.get(feld, feld) for feld in felder])
            for z in zeilen:
                w.writerow(["" if v is None else str(v).replace(".", ",") if feld in KOMMAZAHLEN else v
                            for feld, v in zip(felder, z)])
        anzahl[datei] = len(zeilen)
    return anzahl


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=1))
