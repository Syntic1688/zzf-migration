"""Einrichtung der Testinstanz vor der Migration (Abschnitt 3.4.3).

Richtet in einer leeren Odoo-19-Datenbank mit den Apps Verkauf, Lager und Einkauf die
Anpassungen aus Abschnitt 3.3.4 ein, und zwar über die Schnittstelle, damit sich die
Einrichtung wiederholen lässt:

  1. Einstellungen: Maßeinheiten, Preislisten, Lagerorte
  2. Zusatzfeld x_name_zh „Chinesischer Name“ beim Kontakt, sichtbar im Formular und in der Suche
  3. Wareneingang nur mit Lieferant: Pflichtfeld im Formular und Automatisierungsregel
  4. Lieferschein mit Preisen, beiden Kundennamen, beiden Artikelbezeichnungen und Gesamtgewicht
  5. Einheit „Einheit(en)“ heißt auf Deutsch „Stück“
  6. Gewichte mit drei Nachkommastellen wie im Altsystem (Odoo rundet sonst auf zwei)

Ein zweiter Lauf ändert nur, was abweicht. In Odoo Online lassen sich dieselben Anpassungen
mit Studio vornehmen.

Aufruf: ODOO_URL=… ODOO_DB=… ODOO_KEY=… python3 -I einrichten.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from odoo_api import Odoo  # noqa: E402

PARTNER_FORM = """<data>
  <xpath expr="//h1" position="after">
    <div class="d-flex align-items-baseline w-md-75">
      <span class="me-2 text-muted">中文</span>
      <field name="x_name_zh" class="w-100" placeholder="Chinesischer Name"/>
    </div>
  </xpath>
</data>"""

PARTNER_SUCHE = """<data>
  <field name="name" position="after">
    <field name="x_name_zh"/>
  </field>
</data>"""

WARENEINGANG_FORM = """<data>
  <xpath expr="//group/group/field[@name='partner_id']" position="attributes">
    <attribute name="required">picking_type_code == 'incoming'</attribute>
  </xpath>
</data>"""

REGEL_CODE = """for picking in records:
    if picking.picking_type_code == 'incoming' and not picking.partner_id:
        raise UserError("Ein Wareneingang braucht einen Lieferanten.")
"""

# Vorlage des Lieferscheins (QWeb). Sie läuft in Odoo 19 und 20 und findet das Zusatzfeld über seine
# Bezeichnung „Chinesischer Name“. Dieselbe Datei dient für Odoo Online als Importdatei 12.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "lieferschein.xml"), encoding="utf-8") as _f:
    LIEFERSCHEIN = _f.read().strip()


def einrichten(odoo):
    bericht = {}

    def modell_id(name):
        return odoo("ir.model", "search", domain=[["model", "=", name]], limit=1)[0]

    def erstelle_oder_aendere(modell, suche, werte):
        vorhanden = odoo(modell, "search", domain=suche, limit=1)
        if vorhanden:
            odoo(modell, "write", ids=vorhanden, vals=werte)
            return vorhanden[0], "geändert"
        return odoo(modell, "create", vals_list=[werte])[0], "angelegt"

    # 1. Einstellungen
    einstellung = odoo("res.config.settings", "create", vals_list=[{
        "group_uom": True, "group_product_pricelist": True, "group_stock_multi_locations": True}])
    odoo("res.config.settings", "execute", ids=einstellung)
    # die beim Einschalten angelegte Preisliste „Standard“ archivieren; es gelten die Preisgruppen
    standard = odoo("product.pricelist", "search", domain=[["name", "in", ["Default", "Standard"]]])
    if standard:
        odoo("product.pricelist", "action_archive", ids=standard)
    bericht["einstellungen"] = "Maßeinheiten, Preislisten, Lagerorte eingeschaltet"

    # 2. Zusatzfeld für den chinesischen Kundennamen
    partner = modell_id("res.partner")
    if not odoo("ir.model.fields", "search", domain=[["model", "=", "res.partner"], ["name", "=", "x_name_zh"]]):
        odoo("ir.model.fields", "create", vals_list=[{"model_id": partner, "name": "x_name_zh",
                                                      "field_description": "Chinesischer Name", "ttype": "char"}])
    for name, basis, arch in (("zzf.res.partner.form.name_zh", "base.view_partner_form", PARTNER_FORM),
                              ("zzf.res.partner.search.name_zh", "base.view_res_partner_filter", PARTNER_SUCHE),
                              ("zzf.stock.picking.form.lieferant", "stock.view_picking_form", WARENEINGANG_FORM)):
        modell = "stock.picking" if "picking" in basis else "res.partner"
        _, stand = erstelle_oder_aendere("ir.ui.view", [["name", "=", name]], {
            "name": name, "model": modell, "inherit_id": odoo.kennung(basis), "mode": "extension",
            "arch_db": arch})
        bericht[name] = stand

    # 3. Wareneingang nur mit Lieferant: auch serverseitig, damit kein Import und keine Schnittstelle ihn umgeht
    regel, stand = erstelle_oder_aendere("base.automation", [["name", "=", "ZZF: Wareneingang nur mit Lieferant"]], {
        "name": "ZZF: Wareneingang nur mit Lieferant", "model_id": modell_id("stock.picking"),
        "trigger": "on_create_or_write", "filter_domain": "[('picking_type_code', '=', 'incoming')]"})
    aktion = odoo("ir.actions.server", "search", domain=[["base_automation_id", "=", regel]])
    werte = {"name": "Lieferant prüfen", "model_id": modell_id("stock.picking"), "state": "code",
             "code": REGEL_CODE, "base_automation_id": regel, "usage": "base_automation"}
    if aktion:
        odoo("ir.actions.server", "write", ids=aktion, vals=werte)
    else:
        odoo("ir.actions.server", "create", vals_list=[werte])
    bericht["automatisierungsregel"] = stand

    # 4. Lieferschein als eigener Bericht beim Lieferauftrag
    _, stand = erstelle_oder_aendere("ir.ui.view", [["key", "=", "zzf.lieferschein"]], {
        "name": "zzf.lieferschein", "type": "qweb", "key": "zzf.lieferschein", "arch_db": LIEFERSCHEIN})
    bericht["lieferschein_vorlage"] = stand
    _, stand = erstelle_oder_aendere("ir.actions.report", [["report_name", "=", "zzf.lieferschein"]], {
        "name": "Lieferschein ZZF", "model": "stock.picking", "report_type": "qweb-pdf",
        "report_name": "zzf.lieferschein",
        "binding_model_id": modell_id("stock.picking"), "binding_type": "report",
        "print_report_name": "'Lieferschein - %s' % object.name"})
    bericht["lieferschein_bericht"] = stand

    # 5. Einheit „Stück“ statt „Einheit(en)“ in der deutschen Oberfläche
    odoo("uom.uom", "write", ids=[odoo.kennung("uom.product_uom_unit")], vals={"name": "Stück"},
         context={"lang": "de_DE"})
    bericht["einheit"] = "Einheit(en) heißt auf Deutsch Stück"

    # 6. Gewichte mit drei Nachkommastellen, sonst würde z. B. 0,454 kg zu 0,45 kg gerundet
    odoo("decimal.precision", "write", ids=[odoo.kennung("product.decimal_stock_weight")], vals={"digits": 3})
    bericht["gewicht"] = "Gewicht mit drei Nachkommastellen"
    return bericht


if __name__ == "__main__":
    print(json.dumps(einrichten(Odoo()), ensure_ascii=False, indent=1))
