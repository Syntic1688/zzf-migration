# Prüft die Importdateien wie beim Import über die Oberfläche (base_import, gleicher Codepfad).
# Ausführen in "odoo-bin shell" mit IMPORT_DIR=<Ordner>; gibt nur Anzahlen und Meldungen aus.
import os
import collections

ordner = os.environ["IMPORT_DIR"]
OPTIONEN = {"quoting": '"', "separator": ",", "has_headers": True, "encoding": "utf-8",
            "date_format": "", "datetime_format": "", "float_thousand_separator": os.environ.get("TAUSENDER", ","),
            "float_decimal_separator": os.environ.get("DEZIMAL", "."), "advanced": True, "keep_matches": False,
            "name_create_enabled_fields": {}, "import_set_empty_fields": [], "import_skip_records": [],
            "fallback_values": {}, "skip": 0, "limit": 2000, "tracking_disable": True}

# 1. Einstellungen wie in der Anleitung: Einheiten, Preislisten, Lagerorte
env["res.config.settings"].create({"group_uom": True, "group_product_pricelist": True,
                                   "group_stock_multi_locations": True}).execute()
# 2. Zusatzfeld für den chinesischen Kundennamen
FELD = os.environ.get("FELDNAME", "x_name_zh")
if FELD not in env["res.partner"]._fields:
    env["ir.model.fields"].create({"model_id": env["ir.model"]._get_id("res.partner"), "name": FELD,
                                   "field_description": "Chinesischer Name", "ttype": "char"})
env.ref("product.decimal_stock_weight").digits = 3  # wie Schritt 2, Teil C
env.cr.commit()

DATEIEN = [("01_einheiten.csv", "uom.uom", "de_DE"), ("02_produktkategorien.csv", "product.category", "de_DE"),
           ("03_lagerorte.csv", "stock.location", "de_DE"), ("04_einlagerungsregeln.csv", "stock.putaway.rule", "de_DE"),
           ("05_preislisten.csv", "product.pricelist", "de_DE"), ("06_lieferanten.csv", "res.partner", "de_DE"),
           ("07_ansprechpartner.csv", "res.partner", "de_DE"), ("08_kunden.csv", "res.partner", "de_DE"),
           ("09_produkte.csv", "product.template", "de_DE"), ("10_produkte_chinesisch.csv", "product.template", "zh_CN"),
           ("11_preislisteneintraege.csv", "product.pricelist.item", "de_DE")]
ergebnis = {}
for datei, modell, sprache in DATEIEN:
    e = env(context=dict(env.context, lang=sprache, tz="Europe/Vienna"))
    with open(os.path.join(ordner, datei), "rb") as f:
        inhalt = f.read()
    try:  # ab Odoo 20 erwartet das ORM für Binärfelder einen BinaryBytes-Wert
        from odoo.tools.binary import BinaryBytes
        inhalt = BinaryBytes(inhalt)
    except ImportError:
        pass
    imp = e["base_import.import"].create({"res_model": modell, "file": inhalt, "file_name": datei,
                                          "file_type": "text/csv"})
    vorschau = imp.parse_preview(dict(OPTIONEN))
    if vorschau.get("error"):
        ergebnis[datei] = ("Vorschau-Fehler", vorschau["error"])
        continue
    kopf = vorschau["headers"]
    zuordnung = vorschau["matches"]
    felder = ["/".join(zuordnung[i]) if i in zuordnung else False for i in range(len(kopf))]
    nicht_erkannt = [k for k, f in zip(kopf, felder) if not f]
    res = imp.execute_import(felder, kopf, dict(OPTIONEN))
    meldungen = collections.Counter((m["type"], m["message"][:110]) for m in res.get("messages", []))
    ergebnis[datei] = (len(res.get("ids") or []), nicht_erkannt, dict(meldungen))
    env.cr.commit()

for datei, r in ergebnis.items():
    print(datei, "->", r)

# 3. Nach dem Import: Standardpreisliste archivieren (Preisgruppe 0 steht durch die Reihenfolge vorne)
xid = lambda n: env.ref("__import__." + n)
standard = env["product.pricelist"].search([("id", "not in", [xid(f"zzf_preisliste_{g}").id for g in (0, 2, 3, 5, 8)])])
standard.action_archive()
env.cr.commit()

# 4. Stichproben
P = env["product.template"]
alle = P.search([("default_code", "!=", False)])
print("Produkte:", len(alle), "| lagerfähig:", sum(alle.mapped("is_storable")),
      "| Einheiten:", dict(collections.Counter(alle.with_context(lang="de_DE").mapped("uom_id.name"))))
print("Steuern Verkauf:", dict(collections.Counter(alle.mapped(lambda p: p.taxes_id.name))),
      "| Einkauf:", dict(collections.Counter(alle.mapped(lambda p: p.supplier_taxes_id.name))))
zh = alle.with_context(lang="zh_CN"); de = alle.with_context(lang="de_DE")
print("Namen zh ≠ de:", sum(1 for a, b in zip(zh, de) if a.name != b.name), "| Kategorien:",
      dict(collections.Counter(alle.mapped("categ_id.name"))))
R = env["res.partner"]
kunden = R.search([("customer_rank", ">", 0), ("ref", "!=", False)])
print("Kunden:", len(kunden), "| mit chin. Namen:", len(kunden.filtered(FELD)),
      "| Preislisten:", dict(collections.Counter(kunden.mapped("property_product_pricelist.name"))),
      "| Länder:", dict(collections.Counter(kunden.mapped("country_id.code"))))
lief = R.search([("supplier_rank", ">", 0)])
print("Lieferanten:", len(lief), "| Ansprechpartner:", len(lief.mapped("child_ids")))
print("Preislisteneinträge:", dict(collections.Counter(env["product.pricelist.item"].search([]).mapped("pricelist_id.name"))))
print("Einlagerungsregeln:", [(r.category_id.name, r.location_out_id.complete_name) for r in env["stock.putaway.rule"].search([])])
# Preis für einen Kunden der Gruppe 2: Gruppenpreis, wenn vorhanden, sonst Verkaufspreis
item = env["product.pricelist.item"].search([("pricelist_id.name", "=", "Preisgruppe 2")], limit=1)
pl = item.pricelist_id
p = item.product_tmpl_id.product_variant_id
ohne = env["product.product"].search([("default_code", "!=", False), ("id", "not in", pl.item_ids.product_tmpl_id.product_variant_ids.ids)], limit=1)
print("Preis Gruppe 2 mit Eintrag = fester Preis:", pl._get_product_price(p, 1.0) == item.fixed_price,
      "| ohne Eintrag = Verkaufspreis:", pl._get_product_price(ohne, 1.0) == ohne.list_price)
print("applied_on der Einträge:", dict(collections.Counter(i.applied_on for i in env["product.pricelist.item"].search([]))))
print("Kunden je Preisliste:", dict(collections.Counter(p.property_product_pricelist.name for p in kunden)))

# Zahlen gegen die umgewandelten Daten prüfen (Preise, Gewichte, Gruppenpreise)
import json as _json
from decimal import Decimal as _D
_art = {a["xid"]: a for a in _json.load(open(os.environ["UMGEWANDELT"] + "/artikel.json", encoding="utf-8"))}
_fehler = collections.Counter()
for _p in alle:
    _x = _p.get_external_id()[_p.id].split(".", 1)[1]
    _a = _art[_x]
    if _D(str(_p.list_price)).quantize(_D("0.01")) != _D(_a["list_price"]).quantize(_D("0.01")): _fehler["list_price"] += 1
    if _D(str(_p.weight)).quantize(_D("0.001")) != _D(_a["weight"]).quantize(_D("0.001")): _fehler["weight"] += 1
    if _D(str(_p.standard_price)).quantize(_D("0.01")) != _D(_a["standard_price"] or "0").quantize(_D("0.01")): _fehler["standard_price"] += 1
_pl = {p["xid"]: p for p in _json.load(open(os.environ["UMGEWANDELT"] + "/preislisten.json", encoding="utf-8"))}
_soll = sum(_D(e["fixed_price"]) for p in _pl.values() for e in p["eintraege"])
_ist = sum(_D(str(i.fixed_price)).quantize(_D("0.01")) for i in env["product.pricelist.item"].search([]))
print("Zahlenprüfung: Abweichungen", dict(_fehler), "| Gruppenpreise Summe gleich:", _soll == _ist, "| Optionen:", OPTIONEN["float_thousand_separator"], OPTIONEN["float_decimal_separator"])
