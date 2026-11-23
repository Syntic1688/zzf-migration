"""Prüfwerkzeug der Testmigration (Abschnitt 3.4.3).

Misst die Kennzahlen K1 (Vollständigkeit), K2a (Korrektheit je Feld) und K2b (Kontrollsummen)
aus Tabelle 2 und stellt die Stichprobe für die Sichtprüfung K2c zusammen.

Das Werkzeug ist getrennt von der Pipeline programmiert. Es liest die Altdaten mit einem eigenen
Leseprogramm direkt aus der Kopie (altdaten.py), leitet die Sollwerte selbst aus der Festlegung
ab (Tabelle 6, Anhang C) und liest das Zielsystem über die Schnittstelle. Mit der
Pipeline teilt es nur den Aufbau der externen Kennungen (zzf_kunde_<Nummer> usw.).

Aufruf: ODOO_URL=… ODOO_DB=… ODOO_KEY=… python3 -I pruefen.py <Kopie (Ordner HM9)> <Archivordner>
            <Ergebnisordner> [--stichtag JJJJ-MM-TT] [--korrekturen <Datei>] [--protokoll <Datei>]
Rückgabewert 0: alle Zielwerte erreicht; 1: mindestens ein Zielwert verfehlt.
"""
import argparse
import collections
import csv
import datetime
import hashlib
import json
import os
import random
import re
import sys
import urllib.error
import urllib.request
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from altdaten import lies_tabelle, roh, vergleiche_text  # noqa: E402

# ------------------------------------------------------------------ Festlegungen (aus der Arbeit)
AKTIV_TAGE = 365                                          # Abschnitt 3.2
EINHEIT = {"Pa": "Packung", "pa": "Packung", "Kt": "Karton", "Knt": "Karton", "knt": "Karton",
           "Fl": "Flasche", "FL": "Flasche", "fl": "Flasche", "Do": "Dose", "Kue": "Kübel",
           "kue": "Kübel", "Kuebe": "Kübel", "kubel": "Kübel", "kul": "Kübel", "St": "Stück",
           "st": "Stück", "kg": "kg", "Kg": "kg", "Sa": "Sack"}   # Tabelle C3; Kilogramm heißt in Odoo kg
EINHEIT_FEHLT = "Stück"                                   # R12
STEUERSATZ = {"A": 20.0, "B": 10.0}                       # Tabelle C2
LAGERORT = {"1": "Trockenlager", "2": "Tiefkühllager"}    # Tabelle C2
KRITISCH = {                                              # Abschnitt 2.4
    "Kunde": {"ref", "name", "x_name_zh", "street", "street2", "zip", "city", "country", "preisliste"},
    "Artikel": {"default_code", "name_de", "name_zh", "einheit", "steuer", "list_price", "gruppenpreise"},
    "Lieferant": set(), "Ansprechpartner": set(),
}
KORREKTUR_FELD = {("Kunde", "Name"): "name", ("Kunde", "Chinesischer Name"): "x_name_zh",
                  ("Kunde", "Land"): "country", ("Kunde", "Postleitzahl"): "zip", ("Kunde", "Ort"): "city",
                  ("Kunde", "Straße"): "street", ("Kunde", "Telefon"): "phone", ("Kunde", "Nummer"): "ref",
                  ("Lieferant", "Name"): "name", ("Lieferant", "Land"): "country",
                  ("Lieferant", "Postleitzahl"): "zip", ("Lieferant", "Ort"): "city",
                  ("Lieferant", "Straße"): "street", ("Lieferant", "Telefon"): "phone",
                  ("Artikel", "Name"): "name_de", ("Artikel", "Chinesischer Name"): "name_zh",
                  ("Artikel", "Einheit"): "einheit", ("Artikel", "Gewicht"): "weight",
                  ("Artikel", "Verkaufspreis"): "list_price", ("Artikel", "Einkaufspreis"): "standard_price"}


def xid(art, nummer):
    return f"zzf_{art}_" + re.sub(r"[^0-9A-Za-z]", "_", nummer)


# ------------------------------------------------------------------ Schnittstelle (eigener kleiner Zugriff)
class Ziel:
    def __init__(self):
        self.url, self.db, self.key = os.environ["ODOO_URL"].rstrip("/"), os.environ["ODOO_DB"], os.environ["ODOO_KEY"]
        self.oeffner = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def __call__(self, modell, methode, **kw):
        req = urllib.request.Request(f"{self.url}/json/2/{modell}/{methode}", data=json.dumps(kw).encode(),
                                     headers={"Authorization": f"bearer {self.key}", "X-Odoo-Database": self.db,
                                              "Content-Type": "application/json", "User-Agent": "zzf-pruefwerkzeug"})
        try:
            with self.oeffner.open(req, timeout=600) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{modell}.{methode}: {e.code} {e.read()[:500]!r}") from None


# ------------------------------------------------------------------ Soll aus den Altdaten
def zahl(b):
    s = b.decode("ascii").strip()
    return Decimal(s) if s else Decimal(0)


def datum(b):
    s = b.decode("ascii").strip()
    return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8])) if s else None


def bytes_norm(b):
    """Für den Adressvergleich: Kleinbuchstaben, nur Buchstaben und Ziffern (Sonderzeichen bleiben)."""
    return bytes(c for c in roh(b).lower() if chr(c).isalnum() or c >= 0x80)


def land_plz(b):
    """R6: (Land, Postleitzahl im Zielsystem als Bytes) aus der Postleitzahl des Altsystems."""
    s = roh(b)
    m = re.fullmatch(rb"(?:A-)?(\d{4})", s)
    if m:
        return "AT", m.group(1)
    m = re.fullmatch(rb"(?:D-)?(\d{5})", s)
    if m:
        return "DE", m.group(1)
    return None, s


def soll_ermitteln(kopie, stichtag, korrekturen):
    _, K = lies_tabelle(kopie, "KUNDEN.DBF")
    _, W = lies_tabelle(kopie, "WAREN.DBF")
    _, L = lies_tabelle(kopie, "LIEFER.DBF")
    _, LH = lies_tabelle(kopie, "LIF/LH*.DBF")
    _, LD = lies_tabelle(kopie, "LIF/LD*.DBF")
    stichtag = stichtag or max(datum(r["LDATUM"]) for r in LH)
    ab = stichtag - datetime.timedelta(days=AKTIV_TAGE)
    LH_z = [r for r in LH if ab < datum(r["LDATUM"]) <= stichtag]
    LD_z = [r for r in LD if ab < datum(r["DATUM"]) <= stichtag]
    soll = {}  # externe Kennung -> {"objekt", "quelle", "felder": {feld: (art, wert)}}

    def text(b):
        return ("text", roh(b))

    # Kunden
    nummern = {roh(r["NUM"]) for r in K}
    aktiv = {roh(r["NUM"]) for r in LH_z if roh(r["NUM"]) in nummern}
    nur_ls = collections.defaultdict(list)
    for r in LH_z:
        n = roh(r["NUM"])
        if n and n not in nummern:
            nur_ls[n].append(r)
    angelegt = {}
    for n, saetze in nur_ls.items():
        letzter = max(saetze, key=lambda r: (r["LDATUM"], r["ZEIT"], r["_datei"], r["_satz"]))
        treffer = {roh(k["NUM"]) for k in K if roh(k["NUM"]).lstrip(b"0") == n.lstrip(b"0")
                   and roh(k["ZIP"]) == roh(letzter["ZIP"]) and bytes_norm(k["ADDR"]) == bytes_norm(letzter["ADDR"])}
        if len(treffer) == 1:
            aktiv |= treffer                      # R2: zugeordnet
        else:
            angelegt[n] = letzter                 # R2: aus dem letzten Lieferschein angelegt
    zaehler = collections.Counter()
    kunden = []
    for r in K:
        n = roh(r["NUM"])
        if n in aktiv:
            zaehler[n] += 1
            ref = n.decode("ascii") + ("" if zaehler[n] == 1 else f"-{zaehler[n]}")   # R7
            kunden.append((ref, r, f"KUNDEN.DBF:{r['_satz']}"))
    for n, r in sorted(angelegt.items()):
        kunden.append((n.decode("ascii"), r, f"{r['_datei']}:{r['_satz']}"))
    gruppen = set()
    for ref, r, quelle in kunden:
        land, plz = land_plz(r["ZIP"])
        name = roh(r["WNAME"]) or roh(r["CNAME"])
        gruppe = zahl(r["PRGRP"])
        gruppen.add(int(gruppe))
        soll[xid("kunde", ref)] = {"objekt": "Kunde", "quelle": quelle, "nummer": ref, "felder": {
            "ref": ("wert", ref),
            "name": ("text", name) if name else ("wert", f"Kunde {ref}"),          # R9
            "x_name_zh": text(r["CNAME"]), "street": text(r["ADDR"]), "street2": text(r["WNAME2"]),
            "zip": ("text", plz), "city": text(r["CITY"]), "country": ("wert", land),
            "phone": text(r["TELE"]) if "TELE" in r else ("wert", ""), "vat": text(r["UID"]),
            "preisliste": ("wert", f"Preisgruppe {int(gruppe)}"),
            "rang": ("wert", (1, 0))}}

    # Lieferanten (alle) mit Ansprechpartner
    for r in L:
        n = roh(r["NUM"]).decode("ascii")
        land, plz = land_plz(r["ZIP"])
        soll[xid("lieferant", n)] = {"objekt": "Lieferant", "quelle": f"LIEFER.DBF:{r['_satz']}", "nummer": n,
                                     "felder": {"ref": ("wert", n), "name": text(r["WNAME"]), "street": text(r["ADDR"]),
                                                "zip": ("text", plz), "city": text(r["CITY"]), "country": ("wert", land),
                                                "phone": text(r["TELE"]), "rang": ("wert", (0, 1))}}
        if roh(r["PERSON"]):
            soll[xid("lieferant", n) + "_kontakt"] = {
                "objekt": "Ansprechpartner", "quelle": f"LIEFER.DBF:{r['_satz']}", "nummer": n,
                "felder": {"name": text(r["PERSON"]), "parent": ("wert", xid("lieferant", n))}}

    # Artikel: verkaufte
    artikelnummern = {roh(r["NR"]) for r in W}
    verkauft = {roh(r["NR"]) for r in LD_z if roh(r["NR"]) in artikelnummern}
    for r in W:
        n = roh(r["NR"])
        if n not in verkauft:
            continue
        nr = n.decode("ascii")
        eht = roh(r["EHT"]).decode("ascii", "replace")
        gp = {g: zahl(r[f"PR_EURO{g}"]) for g in sorted(gruppen) if g != 0 and zahl(r[f"PR_EURO{g}"]) > 0}
        soll[xid("artikel", nr)] = {"objekt": "Artikel", "quelle": f"WAREN.DBF:{r['_satz']}", "nummer": nr, "felder": {
            "default_code": ("wert", nr), "name_de": text(r["BZ_D"]),
            "name_zh": text(r["BZ_C"]) if roh(r["BZ_C"]) else text(r["BZ_D"]),   # ohne Übersetzung gilt der deutsche Name
            "einheit": ("wert", EINHEIT.get(eht, EINHEIT_FEHLT)),
            "steuer": ("wert", STEUERSATZ[roh(r["MWST"]).decode()]),
            "vorsteuer": ("wert", STEUERSATZ[roh(r["MWST"]).decode()]),
            "list_price": ("zahl", zahl(r["PR_EURO0"])), "standard_price": ("zahl", zahl(r["EK_EURO"])),
            "weight": ("zahl", zahl(r["WEIGHT"])), "kategorie": ("wert", LAGERORT.get(roh(r["LAG_NR"]).decode())),
            "lagerfaehig": ("wert", True), "gruppenpreise": ("wert", {f"Preisgruppe {g}": p for g, p in gp.items()})}}

    # Korrekturen der Geschäftsführung ersetzen den Sollwert bzw. schließen Datensätze aus
    ausgeschlossen = []
    for (bereich, nummer, feld), wert in korrekturen.items():
        art = {"Kunde": "kunde", "Lieferant": "lieferant", "Artikel": "artikel"}[bereich]
        if feld == "Dublette":
            gruppe = [x.strip() for x in nummer.split("/")]
            if wert.lower() != "alle":
                ausgeschlossen += [xid(art, x) for x in gruppe if x != wert]
            continue
        k = xid(art, nummer)
        if k not in soll:
            continue
        if feld == "Übernehmen" or wert.lower() == "nicht übernehmen":
            if wert.lower() in ("nein", "nicht übernehmen"):
                ausgeschlossen.append(k)
            continue
        ziel = KORREKTUR_FELD[(bereich, feld)]
        if ziel in ("weight", "list_price", "standard_price"):
            soll[k]["felder"][ziel] = ("zahl", Decimal(wert.replace(",", ".")))
        elif ziel == "einheit":
            soll[k]["felder"][ziel] = ("wert", "kg" if wert == "Kilogramm" else wert)
        elif ziel == "ref":
            soll[k]["felder"]["ref"] = ("wert", wert)
            soll[xid(art, wert)] = soll.pop(k)
        else:
            soll[k]["felder"][ziel] = ("wert", wert)
    for k in ausgeschlossen:
        soll.pop(k, None)
    info = {"stichtag": stichtag.isoformat(), "aktive_kunden": len(aktiv), "angelegt_R2": len(angelegt),
            "verkaufte_artikel": len(verkauft), "ausgeschlossen_korrektur": len(ausgeschlossen),
            "preisgruppen": sorted(gruppen)}
    return soll, info


# ------------------------------------------------------------------ Ist aus dem Zielsystem
def ist_lesen(ziel):
    daten = ziel("ir.model.data", "search_read", domain=[["module", "=", "__import__"], ["name", "=like", "zzf_%"]],
                 fields=["model", "res_id", "name"])
    nach_id = {(d["model"], d["res_id"]): d["name"] for d in daten}
    ids = collections.defaultdict(list)
    for d in daten:
        ids[d["model"]].append(d["res_id"])
    ist = {}
    pf = ["name", "x_name_zh", "ref", "street", "street2", "zip", "city", "country_id", "phone", "vat", "parent_id",
          "customer_rank", "supplier_rank", "property_product_pricelist"]
    laender = {c["id"]: c["code"] for c in ziel("res.country", "search_read", domain=[], fields=["code"])}
    # Name der Preisliste ohne die Währung, die Odoo im angezeigten Namen ergänzt
    preislisten = {p["id"]: p["name"] for p in ziel("product.pricelist", "search_read", domain=[["active", "in", [True, False]]],
                                                     fields=["name"], context={"lang": "de_DE"})}
    for p in ziel("res.partner", "read", ids=ids["res.partner"], fields=pf, context={"lang": "de_DE"}):
        ist[nach_id[("res.partner", p["id"])]] = {
            "ref": p["ref"] or "", "name": p["name"] or "", "x_name_zh": p["x_name_zh"] or "",
            "street": p["street"] or "", "street2": p["street2"] or "", "zip": p["zip"] or "", "city": p["city"] or "",
            "country": laender.get(p["country_id"][0]) if p["country_id"] else None, "phone": p["phone"] or "",
            "vat": p["vat"] or "", "preisliste": preislisten[p["property_product_pricelist"][0]] if p["property_product_pricelist"] else None,
            "rang": (p["customer_rank"], p["supplier_rank"]),
            "parent": nach_id.get(("res.partner", p["parent_id"][0])) if p["parent_id"] else None}
    steuern = {t["id"]: t["amount"] for t in ziel("account.tax", "search_read", domain=[], fields=["amount"])}
    tf = ["default_code", "name", "uom_id", "taxes_id", "supplier_taxes_id", "list_price", "standard_price", "weight",
          "categ_id", "is_storable"]
    de = ziel("product.template", "read", ids=ids["product.template"], fields=tf, context={"lang": "de_DE"})
    zh = {p["id"]: p["name"] for p in ziel("product.template", "read", ids=ids["product.template"], fields=["name"],
                                            context={"lang": "zh_CN"})}
    vorlage_xid = {}
    for p in de:
        k = nach_id[("product.template", p["id"])]
        vorlage_xid[p["id"]] = k
        ist[k] = {"default_code": p["default_code"] or "", "name_de": p["name"], "name_zh": zh[p["id"]],
                  "einheit": p["uom_id"][1] if p["uom_id"] else None,
                  "steuer": sum(steuern[t] for t in p["taxes_id"]), "vorsteuer": sum(steuern[t] for t in p["supplier_taxes_id"]),
                  "list_price": p["list_price"], "standard_price": p["standard_price"], "weight": p["weight"],
                  "kategorie": p["categ_id"][1] if p["categ_id"] else None, "lagerfaehig": p["is_storable"],
                  "gruppenpreise": {}}
    eintraege = ziel("product.pricelist.item", "search_read", domain=[],
                     fields=["pricelist_id", "product_tmpl_id", "fixed_price", "compute_price"], context={"lang": "de_DE"})
    for e in eintraege:
        k = vorlage_xid.get(e["product_tmpl_id"][0]) if e["product_tmpl_id"] else None
        if k:
            ist[k]["gruppenpreise"][preislisten[e["pricelist_id"][0]]] = e["fixed_price"]
    # Datensätze ohne Quellbezug: Kunden, Lieferanten, lagerfähige Produkte und Preiseinträge ohne Kennung
    ohne = {
        "Kontakte": [p for p in ziel("res.partner", "search", domain=["|", ["customer_rank", ">", 0], ["supplier_rank", ">", 0]])
                     if ("res.partner", p) not in nach_id],
        "Produkte": [p for p in ziel("product.template", "search", domain=[["is_storable", "=", True]])
                     if ("product.template", p) not in nach_id],
        "Preiseinträge": [e["id"] for e in eintraege if ("product.pricelist.item", e["id"]) not in nach_id]}
    return ist, ohne


# ------------------------------------------------------------------ Vergleich
def gleich(art, sollwert, istwert):
    if art == "text":
        if istwert in (None, False):
            istwert = ""
        return vergleiche_text(istwert, sollwert)
    if art == "zahl":
        stellen = max(0, -sollwert.as_tuple().exponent, 3)
        return "gleich" if Decimal(str(istwert or 0)).quantize(Decimal(1).scaleb(-stellen)) == \
            sollwert.quantize(Decimal(1).scaleb(-stellen)) else "ungleich"
    if isinstance(sollwert, dict):
        return "gleich" if set(sollwert) == set(istwert) and all(
            Decimal(str(istwert[g])).quantize(Decimal("0.01")) == sollwert[g].quantize(Decimal("0.01")) for g in sollwert) \
            else "ungleich"
    if isinstance(sollwert, tuple):
        istwert = tuple(istwert) if istwert else istwert
    return "gleich" if (sollwert or None) == (istwert or None) else "ungleich"


def anzeigen(art, wert):
    if art == "text":
        return wert.decode("cp437")  # nur zur Anzeige der Original-Bytes
    return str(wert)


def pruefen_ziel(soll, ist, ohne):
    felder = collections.defaultdict(lambda: [0, 0])          # (objekt, feld) -> [geprüft, gleich]
    k1 = collections.defaultdict(lambda: [0, 0])              # objekt -> [soll, gefunden]
    abweichungen, halbe = [], 0
    for k, s in soll.items():
        k1[s["objekt"]][0] += 1
        if k not in ist:
            abweichungen.append([s["objekt"], s["nummer"], "(Datensatz)", "vorhanden", "fehlt"])
            continue
        k1[s["objekt"]][1] += 1
        for feld, (art, wert) in s["felder"].items():
            ergebnis = gleich(art, wert, ist[k].get(feld))
            felder[(s["objekt"], feld)][0] += 1
            if ergebnis.startswith("gleich"):
                felder[(s["objekt"], feld)][1] += 1
                halbe += ergebnis.endswith("halbes Zeichen")
            else:
                abweichungen.append([s["objekt"], s["nummer"], feld, anzeigen(art, wert), str(ist[k].get(feld))])
    ueberzaehlig = [k for k in ist if k not in soll and not k.startswith(("zzf_einheit", "zzf_kategorie", "zzf_lagerort",
                                                                           "zzf_einlagerung", "zzf_preisliste"))]
    return felder, k1, abweichungen, halbe, ueberzaehlig


def pruefen_archiv(kopie, archiv):
    """Vergleicht jede Archivdatei Feld für Feld mit der DBF-Datei und bildet die Kontrollsummen."""
    tabellen = {"Lieferscheine.csv": "LIF/LH*.DBF", "Lieferscheinpositionen.csv": "LIF/LD*.DBF",
                "Wareneingaenge.csv": "EIN/EH*.DBF", "Wareneingangspositionen.csv": "EIN/ED*.DBF",
                "Kunden.csv": "KUNDEN.DBF", "Artikel.csv": "WAREN.DBF", "Lieferanten.csv": "LIEFER.DBF",
                "Lagerposten.csv": "FIFO.DBF"}
    summen_felder = {"Lieferscheine.csv": ["ENDSUM", "NETSUM"], "Lieferscheinpositionen.csv": ["MENGE"],
                     "Wareneingaenge.csv": ["ENDSUM", "NETSUM"], "Wareneingangspositionen.csv": ["MENGE"]}
    ergebnis, abweichungen = {}, []
    inhalt = {z["datei"]: z for z in csv.DictReader(open(os.path.join(archiv, "inhalt.csv"), encoding="utf-8"))}
    for datei, muster in tabellen.items():
        felder, quelle = lies_tabelle(kopie, muster)
        pfad = os.path.join(archiv, datei)
        with open(pfad, "rb") as f:
            pruefsumme_ok = hashlib.sha256(f.read()).hexdigest() == inhalt.get(datei, {}).get("sha256")
        with open(pfad, encoding="utf-8", newline="") as f:
            zeilen = list(csv.DictReader(f))
        geprueft = gleich_anz = halbe = 0
        for q, z in zip(quelle, zeilen):
            if (z["_datei"], int(z["_satz"])) != (q["_datei"], q["_satz"]):
                abweichungen.append([datei, z["_datei"], z["_satz"], "Herkunft", "verschoben"])
                continue
            for name, typ, _laenge, _nk in felder:
                b, w = q[name], z[name]
                if typ == "C":
                    e = vergleiche_text(w, b)
                    halbe += e.endswith("halbes Zeichen")
                    ok = e.startswith("gleich")
                elif typ == "N":
                    ok = (Decimal(w) if w else None) == (Decimal(b.decode().strip()) if b.strip() else None)
                elif typ == "D":
                    ok = w == (datum(b).isoformat() if b.strip() else "")
                elif typ == "L":
                    ok = w == {b"T": "true", b"t": "true", b"Y": "true", b"y": "true", b"F": "false", b"f": "false",
                               b"N": "false", b"n": "false"}.get(b.strip(), "")
                else:
                    ok = False
                geprueft += 1
                gleich_anz += ok
                if not ok:
                    abweichungen.append([datei, q["_datei"], q["_satz"], name, w])
        summen = {}
        for feld in summen_felder.get(datei, []):
            summen[feld] = {"quelle": str(sum(zahl(q[feld]) for q in quelle)),
                            "archiv": str(sum(Decimal(z[feld] or 0) for z in zeilen))}
        ergebnis[datei] = {"datensaetze_quelle": len(quelle), "datensaetze_archiv": len(zeilen),
                           "felder_geprueft": geprueft, "felder_gleich": gleich_anz, "halbe_zeichen": halbe,
                           "pruefsumme_unveraendert": pruefsumme_ok, "summen": summen}
    return ergebnis, abweichungen


def pruefen_protokoll(kopie, pfad):
    """Je Datensatz des Altsystems genau eine Zeile im Protokoll der Pipeline (Datei und Satznummer)."""
    quelle = collections.Counter()
    for muster in ("KUNDEN.DBF", "WAREN.DBF", "LIEFER.DBF", "FIFO.DBF", "LIF/LH*.DBF", "LIF/LD*.DBF",
                   "EIN/EH*.DBF", "EIN/ED*.DBF"):
        for r in lies_tabelle(kopie, muster)[1]:
            quelle[(r["_datei"], r["_satz"])] += 1
    with open(pfad, encoding="utf-8", newline="") as f:
        zeilen = collections.Counter((z["datei"], int(z["satz"])) for z in csv.DictReader(f))
    return {"datensaetze_quelle": sum(quelle.values()), "zeilen_protokoll": sum(zeilen.values()),
            "ohne_zeile": sum(1 for k in quelle if k not in zeilen),
            "mehrfach_oder_fremd": sum(1 for k, n in zeilen.items() if n > 1 or k not in quelle)}


def stichprobe(soll, seed=2026):
    """K2c: je Objekttyp 20 Sonderfälle und 30 Zufallsfälle für die Sichtprüfung am Bildschirm."""
    zeilen = []
    zufall = random.Random(seed)
    for objekt in ("Kunde", "Artikel", "Lieferant"):
        alle = sorted((k for k, s in soll.items() if s["objekt"] == objekt), key=lambda k: soll[k]["nummer"])
        gruende = {}
        for k in alle:
            f = soll[k]["felder"]
            g = []
            if objekt == "Kunde":
                if f["name"][0] == "wert":
                    g.append("ohne Namen")
                elif f["name"] == f["x_name_zh"]:
                    g.append("nur chinesischer Name")
                if f["country"][1] is None:
                    g.append("Land offen")
                if "-" in soll[k]["nummer"]:
                    g.append("Nummer doppelt")
                if soll[k]["quelle"].startswith("LH"):
                    g.append("nur im Lieferschein")
                if f["preisliste"][1] != "Preisgruppe 0":
                    g.append(f["preisliste"][1])
            if objekt == "Artikel":
                if f["gruppenpreise"][1]:
                    g.append("Gruppenpreis")
                if f["weight"][1] == 0:
                    g.append("ohne Gewicht")
                elif f["weight"][1] != f["weight"][1].quantize(Decimal("0.01")):
                    g.append("Gewicht mit drei Stellen")
                if f["list_price"][1] == 0:
                    g.append("ohne Verkaufspreis")
                if f["name_zh"] == f["name_de"]:
                    g.append("ohne chinesischen Namen")
            if objekt == "Lieferant":
                if f["country"][1] is None:
                    g.append("Land offen")
                if (xid("lieferant", soll[k]["nummer"]) + "_kontakt") in soll:
                    g.append("mit Ansprechpartner")
            if g:
                gruende[k] = ", ".join(g)
        # Sonderfälle reihum aus jeder Art von Sonderfall wählen, damit alle Arten vorkommen
        arten = collections.defaultdict(list)
        for k in sorted(gruende, key=lambda k: soll[k]["nummer"]):
            for g in gruende[k].split(", "):
                arten[g].append(k)
        sonder = []
        while len(sonder) < 20 and any(arten.values()):
            for g in sorted(arten):
                while arten[g] and arten[g][0] in sonder:
                    arten[g].pop(0)
                if arten[g] and len(sonder) < 20:
                    sonder.append(arten[g].pop(0))
        rest = [k for k in alle if k not in sonder]
        auswahl = [(k, "Sonderfall: " + gruende[k]) for k in sonder] + \
                  [(k, "Zufall") for k in zufall.sample(rest, min(30, len(rest)))]
        for k, grund in auswahl:
            zeilen.append({"Objekt": objekt, "Nummer": soll[k]["nummer"], "Auswahl": grund,
                           "Quelle": soll[k]["quelle"], "Ergebnis (ok/Fehler)": "", "Bemerkung": ""})
    return zeilen


def lade_korrekturen(pfad):
    if not pfad:
        return {}
    with open(pfad, encoding="utf-8-sig", newline="") as f:
        kopf = f.readline()
        f.seek(0)
        zeilen = csv.DictReader(f, delimiter=";" if kopf.count(";") > kopf.count(",") else ",")
        return {(z["Bereich"].strip(), z["Nummer"].strip(), z["Feld"].strip()): z["Entscheidung"].strip()
                for z in zeilen if (z.get("Entscheidung") or "").strip()}


def main():
    p = argparse.ArgumentParser(description="Prüfwerkzeug der Testmigration")
    p.add_argument("kopie")
    p.add_argument("archiv")
    p.add_argument("ergebnis")
    p.add_argument("--stichtag", type=datetime.date.fromisoformat)
    p.add_argument("--korrekturen")
    p.add_argument("--protokoll", help="protokoll.csv der Pipeline")
    a = p.parse_args()
    os.makedirs(a.ergebnis, exist_ok=True)

    soll, info = soll_ermitteln(a.kopie, a.stichtag, lade_korrekturen(a.korrekturen))
    ist, ohne = ist_lesen(Ziel())
    felder, k1, abw_ziel, halbe, ueberzaehlig = pruefen_ziel(soll, ist, ohne)
    archiv, abw_archiv = pruefen_archiv(a.kopie, a.archiv)
    protokoll = pruefen_protokoll(a.kopie, a.protokoll) if a.protokoll else None

    # Kennzahlen
    K1 = {o: {"soll": n, "gefunden": g, "quote": round(100 * g / n, 2) if n else 100.0} for o, (n, g) in k1.items()}
    K1["Archiv"] = {"soll": sum(v["datensaetze_quelle"] for v in archiv.values()),
                    "gefunden": sum(min(v["datensaetze_archiv"], v["datensaetze_quelle"]) for v in archiv.values())}
    K1["Archiv"]["quote"] = round(100 * K1["Archiv"]["gefunden"] / K1["Archiv"]["soll"], 2)
    ohne_bezug = sum(len(v) for v in ohne.values()) + len(ueberzaehlig)
    K2a = {f"{o}.{f}": {"geprueft": n, "gleich": g, "quote": round(100 * g / n, 2), "kritisch": f in KRITISCH[o]}
           for (o, f), (n, g) in sorted(felder.items())}
    K2a["Archiv (alle Felder)"] = {"geprueft": sum(v["felder_geprueft"] for v in archiv.values()),
                                   "gleich": sum(v["felder_gleich"] for v in archiv.values()), "kritisch": False}
    K2a["Archiv (alle Felder)"]["quote"] = round(100 * K2a["Archiv (alle Felder)"]["gleich"]
                                                 / K2a["Archiv (alle Felder)"]["geprueft"], 4)
    zaehl = collections.Counter(s["objekt"] for s in soll.values())
    ist_zaehl = collections.Counter(soll[k]["objekt"] for k in ist if k in soll)
    gp_soll = collections.defaultdict(lambda: [0, Decimal(0)])
    gp_ist = collections.defaultdict(lambda: [0, Decimal(0)])
    for k, s in soll.items():
        if s["objekt"] == "Artikel":
            for g, preis in s["felder"]["gruppenpreise"][1].items():
                gp_soll[g][0] += 1
                gp_soll[g][1] += preis
            for g, preis in ist.get(k, {}).get("gruppenpreise", {}).items():
                gp_ist[g][0] += 1
                gp_ist[g][1] += Decimal(str(preis)).quantize(Decimal("0.01"))
    K2b = {"Datensätze je Objekttyp": {o: {"quelle": zaehl[o], "ziel": ist_zaehl[o]} for o in sorted(zaehl)},
           "Gruppenpreise": {g: {"quelle": [gp_soll[g][0], str(gp_soll[g][1])], "ziel": [gp_ist[g][0], str(gp_ist[g][1])]}
                             for g in sorted(set(gp_soll) | set(gp_ist))},
           "Verkaufspreise (Summe)": {"quelle": str(sum(s["felder"]["list_price"][1] for s in soll.values()
                                                        if s["objekt"] == "Artikel")),
                                      "ziel": str(sum(Decimal(str(ist[k]["list_price"])).quantize(Decimal("0.01"))
                                                      for k, s in soll.items() if s["objekt"] == "Artikel" and k in ist))},
           "Archiv": {d: {"datensaetze": [v["datensaetze_quelle"], v["datensaetze_archiv"]], **v["summen"]}
                      for d, v in archiv.items()}}
    k2b_diff = sum(1 for v in K2b["Datensätze je Objekttyp"].values() if v["quelle"] != v["ziel"]) + \
        sum(1 for v in K2b["Gruppenpreise"].values() if v["quelle"] != v["ziel"]) + \
        (K2b["Verkaufspreise (Summe)"]["quelle"] != K2b["Verkaufspreise (Summe)"]["ziel"]) + \
        sum(1 for v in archiv.values() if v["datensaetze_quelle"] != v["datensaetze_archiv"]
            or any(s["quelle"] != s["archiv"] for s in v["summen"].values()))
    ziele = {
        "K1": all(v["quote"] == 100.0 for v in K1.values()) and ohne_bezug == 0,
        "K2a": all(v["quote"] == 100.0 for v in K2a.values() if v["kritisch"])
               and all(v["quote"] >= 99.0 for v in K2a.values() if not v["kritisch"]),
        "K2b": k2b_diff == 0,
        "Archiv unverändert": all(v["pruefsumme_unveraendert"] for v in archiv.values()),
    }
    if protokoll:
        ziele["Protokoll je Datensatz"] = protokoll["ohne_zeile"] == 0 and protokoll["mehrfach_oder_fremd"] == 0
    bericht = {"soll": info, "zielwerte_erreicht": ziele, "K1": K1, "ohne_quellbezug": {
        **{k: len(v) for k, v in ohne.items()}, "Kennungen ohne Soll": len(ueberzaehlig)},
        "K2a": K2a, "K2b": K2b, "halbe_zeichen": {"ziel": halbe, "archiv": sum(v["halbe_zeichen"] for v in archiv.values())},
        "abweichungen": {"ziel": len(abw_ziel), "archiv": len(abw_archiv)}, "protokoll": protokoll}
    with open(os.path.join(a.ergebnis, "bericht.json"), "w", encoding="utf-8") as f:
        json.dump(bericht, f, ensure_ascii=False, indent=1)
    with open(os.path.join(a.ergebnis, "abweichungen.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bereich", "nummer", "feld", "soll", "ist"])
        w.writerows(abw_ziel)
        w.writerows([["Archiv " + d, f"{q}:{s}", feld, "", wert] for d, q, s, feld, wert in abw_archiv])
    with open(os.path.join(a.ergebnis, "sichtpruefung.csv"), "w", encoding="utf-8-sig", newline="") as f:
        zeilen = stichprobe(soll)
        w = csv.DictWriter(f, fieldnames=list(zeilen[0]), delimiter=";")
        w.writeheader()
        w.writerows(zeilen)
    kurz = {"zielwerte_erreicht": ziele, "K1": {o: v["quote"] for o, v in K1.items()}, "ohne_quellbezug": ohne_bezug,
            "K2a_unter_100": {k: v["quote"] for k, v in K2a.items() if v["quote"] < 100},
            "K2b_abweichungen": k2b_diff, "abweichungen": bericht["abweichungen"], "halbe_zeichen": bericht["halbe_zeichen"],
            "protokoll": protokoll}
    print(json.dumps(kurz, ensure_ascii=False, indent=1))
    return 0 if all(ziele.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
