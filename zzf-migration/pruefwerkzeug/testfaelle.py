"""Prozess-Testfälle in der Testinstanz nach der Migration (Kennzahl K5, Abschnitt 3.5.3).

Prüft die Abnahmekriterien der Must-Anforderungen F1, F3, F4, D2, D3 und T2 aus Tabelle A2 mit
übernommenen Kunden und Artikeln. Aufträge, Lieferungen und Wareneingänge entstehen über die
Schnittstelle; den Lieferschein liefert Odoo als PDF wie beim Drucken in der Oberfläche.
Ausgegeben werden je Testfall bestanden/nicht bestanden und die geprüften Werte ohne
Kundendaten.

Aufruf: ODOO_URL=… ODOO_DB=… ODOO_KEY=… ODOO_PASSWORT=… python3 -I testfaelle.py <Ergebnisordner>
"""
import http.cookiejar
import json
import os
import re
import sys
import urllib.request
from html import unescape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pruefen import Ziel  # noqa: E402


def lieferschein_text(picking_id):
    """Meldet sich wie ein Benutzer an und lädt den Lieferschein als PDF; gibt den Text zurück."""
    url, db = os.environ["ODOO_URL"].rstrip("/"), os.environ["ODOO_DB"]
    keks = http.cookiejar.CookieJar()
    oeffner = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(keks))
    anmeldung = {"jsonrpc": "2.0", "params": {"db": db, "login": "admin", "password": os.environ.get("ODOO_PASSWORT", "admin")}}
    oeffner.open(urllib.request.Request(f"{url}/web/session/authenticate", data=json.dumps(anmeldung).encode(),
                                        headers={"Content-Type": "application/json"}))
    pdf = oeffner.open(f"{url}/report/pdf/zzf.lieferschein/{picking_id}").read()
    # Den Text liefert die HTML-Fassung desselben Berichts (im PDF sind die lateinischen Schriften
    # nicht als Text auslesbar); Markierungen und Leerraum werden entfernt.
    html = oeffner.open(f"{url}/report/html/zzf.lieferschein/{picking_id}").read().decode("utf-8")
    text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html.split("<main", 1)[-1])))
    return pdf, text


def main(ergebnis):
    z = Ziel()
    os.makedirs(ergebnis, exist_ok=True)
    faelle = {}

    def xid_ids(modell, muster):
        return [d["res_id"] for d in z("ir.model.data", "search_read", domain=[
            ["module", "=", "__import__"], ["model", "=", modell], ["name", "=like", muster]], fields=["res_id"])]

    preisliste = {p["name"]: p["id"] for p in z("product.pricelist", "search_read", domain=[], fields=["name"])}
    lager = z("stock.warehouse", "search_read", domain=[], fields=["lot_stock_id", "in_type_id", "out_type_id"], limit=1)[0]

    # Testdaten: ein Kunde der Preisgruppe 2 mit deutschem und chinesischem Namen
    kunden = z("res.partner", "search_read", domain=[["id", "in", xid_ids("res.partner", "zzf_kunde_%")],
                                                     ["specific_property_product_pricelist", "=", preisliste["Preisgruppe 2"]],
                                                     ["x_name_zh", "!=", False]],
               fields=["name", "x_name_zh"], order="id")
    kunde = next(k for k in kunden if k["name"] != k["x_name_zh"])
    # Artikel mit Preis der Gruppe 2 und Artikel ohne ihn
    eintraege = z("product.pricelist.item", "search_read", domain=[["pricelist_id", "=", preisliste["Preisgruppe 2"]]],
                  fields=["product_tmpl_id", "fixed_price"], order="id")
    mit_gp = [e["product_tmpl_id"][0] for e in eintraege][:2]
    gp_preis = {e["product_tmpl_id"][0]: e["fixed_price"] for e in eintraege}
    ohne_gp = z("product.template", "search", domain=[["id", "in", xid_ids("product.template", "zzf_artikel_%")],
                                                       ["id", "not in", list(gp_preis)], ["list_price", ">", 0],
                                                       ["weight", ">", 0]], limit=3, order="id")
    vorlagen = mit_gp + ohne_gp
    varianten = {v["product_tmpl_id"][0]: v for v in z("product.product", "search_read",
                 domain=[["product_tmpl_id", "in", vorlagen]], fields=["product_tmpl_id", "uom_id", "weight", "lst_price"])}

    # D3: kein Altbestand nach der Migration; Anfangsbestand aus der Inventur
    altbestand = z("stock.quant", "search_count", domain=[["location_id.usage", "=", "internal"]])
    for t in vorlagen:
        q = z("stock.quant", "create", vals_list=[{"product_id": varianten[t]["id"], "location_id": lager["lot_stock_id"][0],
                                                   "inventory_quantity": 50}])
        z("stock.quant", "action_apply_inventory", ids=q)
    bestand = {t: z("product.product", "read", ids=[varianten[t]["id"]], fields=["qty_available"])[0]["qty_available"]
               for t in vorlagen}
    faelle["D3 Bestand per Inventur"] = {"bestanden": altbestand == 0 and all(b == 50 for b in bestand.values()),
                                         "altbestand_posten": altbestand, "anfangsbestand_je_artikel": 50}

    # F1: Preisvorschlag nach Preisgruppe, Preis änderbar und 0 möglich
    zeilen = [[0, 0, {"product_id": varianten[t]["id"], "product_uom_qty": menge}] for t, menge in zip(vorlagen, [2, 3, 4, 1, 5])]
    auftrag = z("sale.order", "create", vals_list=[{"partner_id": kunde["id"], "order_line": zeilen}])[0]
    pos = z("sale.order.line", "search_read", domain=[["order_id", "=", auftrag]], fields=["product_template_id", "price_unit"], order="id")
    vorschlag_ok = all(abs(p["price_unit"] - (gp_preis.get(p["product_template_id"][0])
                                               or varianten[p["product_template_id"][0]]["lst_price"])) < 0.005 for p in pos)
    geaendert, gratis = pos[3], pos[4]
    z("sale.order.line", "write", ids=[geaendert["id"]], vals={"price_unit": round(geaendert["price_unit"] + 1.11, 2)})
    z("sale.order.line", "write", ids=[gratis["id"]], vals={"price_unit": 0})
    z("sale.order", "action_confirm", ids=[auftrag])
    lieferung = z("stock.picking", "search_read", domain=[["sale_id", "=", auftrag]], fields=["name"])[0]
    pdf, text = lieferschein_text(lieferung["id"])
    with open(os.path.join(ergebnis, "lieferschein_test.pdf"), "wb") as f:
        f.write(pdf)
    preis_neu = f"{round(geaendert['price_unit'] + 1.11, 2):.2f}".replace(".", ",")
    faelle["F1 Preise"] = {"bestanden": vorschlag_ok and preis_neu in text and "0,00" in text,
                           "vorschlag_nach_preisgruppe": vorschlag_ok, "positionen_mit_gruppenpreis": len(mit_gp),
                           "positionen_mit_verkaufspreis": len(ohne_gp),
                           "geaenderter_preis_auf_lieferschein": preis_neu in text, "preis_0_auf_lieferschein": "0,00" in text}

    # F3: beide Kundennamen und Gesamtgewicht aus den Artikelgewichten
    gewicht = sum(m * varianten[t]["weight"] for t, m in zip(vorlagen, [2, 3, 4, 1, 5]))
    gewicht_text = f"{gewicht:.2f}".replace(".", ",")
    faelle["F3 Lieferschein"] = {"bestanden": kunde["name"] in text and kunde["x_name_zh"] in text and gewicht_text in text,
                                 "deutscher_name": kunde["name"] in text, "chinesischer_name": kunde["x_name_zh"] in text,
                                 "gesamtgewicht_berechnet_kg": gewicht_text, "gesamtgewicht_auf_lieferschein": gewicht_text in text}

    # F4: Wareneingang ohne Lieferant abgewiesen; Eingang erhöht, Lieferung senkt den Bestand
    t0 = vorlagen[0]
    bewegung = {"product_id": varianten[t0]["id"], "product_uom_qty": 10, "product_uom": varianten[t0]["uom_id"][0],
                "location_id": z("stock.location", "search", domain=[["usage", "=", "supplier"]], limit=1)[0],
                "location_dest_id": lager["lot_stock_id"][0]}
    try:
        z("stock.picking", "create", vals_list=[{"picking_type_id": lager["in_type_id"][0], "move_ids": [[0, 0, dict(bewegung)]]}])
        abgewiesen, meldung = False, ""
    except RuntimeError as e:
        abgewiesen, meldung = "Lieferanten" in str(e), "Ein Wareneingang braucht einen Lieferanten."
    lieferant = xid_ids("res.partner", "zzf_lieferant_%")[0]
    eingang = z("stock.picking", "create", vals_list=[{"picking_type_id": lager["in_type_id"][0], "partner_id": lieferant,
                                                       "move_ids": [[0, 0, dict(bewegung)]]}])[0]
    z("stock.picking", "action_confirm", ids=[eingang])
    for m in z("stock.move", "search_read", domain=[["picking_id", "=", eingang]], fields=["product_uom_qty"]):
        z("stock.move", "write", ids=[m["id"]], vals={"quantity": m["product_uom_qty"], "picked": True})
    z("stock.picking", "button_validate", ids=[eingang])
    nach_eingang = z("product.product", "read", ids=[varianten[t0]["id"]], fields=["qty_available"])[0]["qty_available"]
    ziel_ort = z("stock.move.line", "search_read", domain=[["picking_id", "=", eingang]], fields=["location_dest_id"])[0]
    z("stock.picking", "action_assign", ids=[lieferung["id"]])
    for m in z("stock.move", "search_read", domain=[["picking_id", "=", lieferung["id"]]], fields=["product_uom_qty"]):
        z("stock.move", "write", ids=[m["id"]], vals={"quantity": m["product_uom_qty"], "picked": True})
    z("stock.picking", "button_validate", ids=[lieferung["id"]])
    nach_lieferung = z("product.product", "read", ids=[varianten[t0]["id"]], fields=["qty_available"])[0]["qty_available"]
    faelle["F4 Wareneingang und Bestand"] = {
        "bestanden": abgewiesen and nach_eingang == 60 and nach_lieferung == 58,
        "ohne_lieferant_abgewiesen": abgewiesen, "meldung": meldung if abgewiesen else "",
        "bestand_vorher": 50, "nach_eingang_10": nach_eingang, "nach_lieferung_2": nach_lieferung,
        "einlagerung_in": ziel_ort["location_dest_id"][1]}

    # D2: nur 8 Einheiten und keine doppelte Kundennummer
    artikel = z("product.template", "read", ids=xid_ids("product.template", "zzf_artikel_%"), fields=["uom_id"])
    einheiten = sorted({a["uom_id"][1] for a in artikel})
    refs = [k["ref"] for k in z("res.partner", "read", ids=xid_ids("res.partner", "zzf_kunde_%"), fields=["ref"])]
    faelle["D2 Bereinigung (ohne Prüfliste)"] = {"bestanden": len(einheiten) == 8 and len(refs) == len(set(refs)),
                                                 "einheiten": einheiten, "doppelte_kundennummern": len(refs) - len(set(refs))}

    # T2: Sprache je Benutzer umschaltbar
    benutzer = (z("res.users", "search", domain=[["login", "=", "test.lager"]])
                or z("res.users", "create", vals_list=[{"name": "Test Lager", "login": "test.lager"}]))[0]
    z("res.users", "write", ids=[benutzer], vals={"lang": "zh_CN"})
    sprache = z("res.users", "read", ids=[benutzer], fields=["lang"])[0]["lang"]
    z("res.users", "write", ids=[benutzer], vals={"lang": "de_DE"})
    sprache2 = z("res.users", "read", ids=[benutzer], fields=["lang"])[0]["lang"]
    faelle["T2 Sprache je Benutzer"] = {"bestanden": sprache == "zh_CN" and sprache2 == "de_DE",
                                        "sprachen": [l["code"] for l in z("res.lang", "search_read", domain=[], fields=["code"])]}

    ergebnisse = {"bestanden": sum(f["bestanden"] for f in faelle.values()), "durchgefuehrt": len(faelle), "faelle": faelle}
    with open(os.path.join(ergebnis, "testfaelle.json"), "w", encoding="utf-8") as f:
        json.dump(ergebnisse, f, ensure_ascii=False, indent=1)
    print(json.dumps(ergebnisse, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
