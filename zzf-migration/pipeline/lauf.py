"""Ein vollständiger Migrationslauf: Lesen, Umwandeln, Laden, Archiv und danach die Prüfung.

Aufruf: ODOO_URL=… ODOO_DB=… ODOO_KEY=… python3 -I lauf.py <Kopie (Ordner HM9)> <Arbeitsordner>
            [--stichtag JJJJ-MM-TT] [--korrekturen <Datei>] [--pruefwerkzeug <Pfad zu pruefen.py>]

Im Arbeitsordner entstehen zwischenspeicher/, umgewandelt/, archiv/, pruefung/ und lauf.json mit
der Dauer je Schritt, den Anzahlen und Prüfsummen. Die Prüfsumme des Zielabbilds fasst alle
übernommenen Datensätze zusammen, wie Odoo sie nach dem Laden liefert. Gleiche Prüfsummen in
mehreren Läufen zeigen, dass jeder Lauf dasselbe Ergebnis erzeugt.
"""
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import archiv  # noqa: E402
import laden  # noqa: E402
import lesen  # noqa: E402
import umwandeln  # noqa: E402
from odoo_api import Odoo  # noqa: E402

# Felder, die das Zielabbild je Modell enthält
ABBILD = {
    "uom.uom": ["name"],
    "product.category": ["name"],
    "stock.location": ["name", "location_id"],
    "stock.putaway.rule": ["category_id", "location_in_id", "location_out_id"],
    "product.pricelist": ["name", "sequence"],
    "res.partner": ["name", "x_name_zh", "ref", "street", "street2", "zip", "city", "country_id", "phone", "vat",
                    "parent_id", "customer_rank", "supplier_rank", "property_product_pricelist"],
    "product.template": ["default_code", "name", "uom_id", "categ_id", "taxes_id", "supplier_taxes_id",
                         "list_price", "standard_price", "weight", "is_storable"],
    "product.pricelist.item": ["pricelist_id", "product_tmpl_id", "compute_price", "fixed_price"],
}


def ordnersumme(ordner):
    """Eine Prüfsumme über alle Dateien eines Ordners (Name und Inhalt)."""
    h = hashlib.sha256()
    for name in sorted(os.listdir(ordner)):
        h.update(name.encode())
        with open(os.path.join(ordner, name), "rb") as f:
            h.update(hashlib.sha256(f.read()).digest())
    return h.hexdigest()


def zielabbild(odoo):
    """Liest alle übernommenen Datensätze zurück; Verweise erscheinen als externe Kennung oder Name."""
    xids = odoo("ir.model.data", "search_read", domain=[["module", "=", "__import__"], ["name", "=like", "zzf_%"]],
                fields=["model", "res_id", "name"])
    namen = {(x["model"], x["res_id"]): x["name"] for x in xids}
    abbild = {}
    for modell, felder in ABBILD.items():
        ids = sorted(r for (m, r) in namen if m == modell)
        if not ids:
            continue
        for sprache in (["de_DE", "zh_CN"] if modell == "product.template" else ["de_DE"]):
            for satz in odoo(modell, "read", ids=ids, fields=felder, context={"lang": sprache}):
                eintrag = {}
                for feld in felder:
                    wert = satz[feld]
                    if isinstance(wert, list) and len(wert) == 2 and isinstance(wert[0], int) and isinstance(wert[1], str):
                        wert = wert[1]  # many2one: angezeigter Name
                    elif isinstance(wert, list):
                        wert = sorted(wert)
                    eintrag[feld] = wert
                abbild[f"{namen[(modell, satz['id'])]}@{sprache}"] = eintrag
    text = json.dumps(abbild, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), len(abbild)


def lauf(kopie, arbeit, stichtag=None, korrekturen=None, pruefwerkzeug=None):
    odoo = Odoo()
    ordner = {n: os.path.join(arbeit, n) for n in ("zwischenspeicher", "umgewandelt", "archiv", "pruefung")}
    bericht = {"beginn": datetime.datetime.now().isoformat(timespec="seconds"), "datenbank": odoo.datenbank,
               "schritte": {}}

    def schritt(name, funktion):
        beginn = time.monotonic()
        ergebnis = funktion()
        bericht["schritte"][name] = {"sekunden": round(time.monotonic() - beginn, 1), "ergebnis": ergebnis}
        return ergebnis

    schritt("1 Lesen", lambda: lesen.main(kopie, ordner["zwischenspeicher"]))
    schritt("2 Umwandeln", lambda: umwandeln.umwandeln(ordner["zwischenspeicher"], ordner["umgewandelt"],
                                                        stichtag, korrekturen))
    schritt("3 Laden", lambda: laden.laden(ordner["umgewandelt"], odoo))
    schritt("4 Archiv", lambda: archiv.archivieren(ordner["zwischenspeicher"], ordner["archiv"]))
    if pruefwerkzeug:
        def pruefen():
            befehl = [sys.executable, "-I", pruefwerkzeug, kopie, ordner["archiv"], ordner["pruefung"],
                      "--protokoll", os.path.join(ordner["umgewandelt"], "protokoll.csv")]
            if stichtag:
                befehl += ["--stichtag", stichtag.isoformat()]
            if korrekturen:
                befehl += ["--korrekturen", korrekturen]
            ausgabe = subprocess.run(befehl, capture_output=True, text=True, env=os.environ)
            if ausgabe.returncode not in (0, 1):  # 1 = Prüfung lief, Zielwerte nicht erreicht
                raise RuntimeError(ausgabe.stderr[-2000:])
            return json.loads(ausgabe.stdout)
        schritt("5 Prüfen", pruefen)
    summe, anzahl = zielabbild(odoo)
    bericht["dauer_sekunden"] = round(sum(s["sekunden"] for s in bericht["schritte"].values()), 1)
    bericht["pruefsummen"] = {"umgewandelt": ordnersumme(ordner["umgewandelt"]),
                              "archiv": ordnersumme(ordner["archiv"]),
                              "zielabbild": summe, "zielabbild_datensaetze": anzahl}
    with open(os.path.join(arbeit, "lauf.json"), "w", encoding="utf-8") as f:
        json.dump(bericht, f, ensure_ascii=False, indent=1)
    return bericht


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Vollständiger Migrationslauf")
    p.add_argument("kopie")
    p.add_argument("arbeit")
    p.add_argument("--stichtag", type=datetime.date.fromisoformat)
    p.add_argument("--korrekturen")
    p.add_argument("--pruefwerkzeug")
    a = p.parse_args()
    b = lauf(a.kopie, a.arbeit, a.stichtag, a.korrekturen, a.pruefwerkzeug)
    print(json.dumps({"dauer_sekunden": b["dauer_sekunden"], "pruefsummen": b["pruefsummen"],
                      "schritte": {k: v["sekunden"] for k, v in b["schritte"].items()}}, ensure_ascii=False, indent=1))
