"""Schritt 2 der Migrationspipeline: Umwandeln.

Liest die CSV-Dateien aus dem Zwischenspeicher, wählt die zu übernehmenden Datensätze aus,
ordnet ihre Felder dem Zielsystem zu (Anhang C), wendet die Bereinigungsregeln R1 bis R12
(Tabelle C4) und danach die Korrekturdatei der Geschäftsführung an. In den Zielordner
schreibt es:

  lieferanten.json, kunden.json,      Datensätze für das Laden, Felder wie in Odoo benannt
  artikel.json, preislisten.json
  protokoll.csv                       genau eine Zeile je Datensatz des Altsystems: übernommen,
                                      nicht übernommen oder archiviert, mit Regel und Grund
  pruefliste.csv                      Fälle, die die Geschäftsführung entscheidet, mit dem
                                      vorläufigen Wert und einer Spalte für die Entscheidung
  zusammenfassung.json                Anzahlen je Tabelle und Regel, Stichtag, Prüfsummen der
                                      Eingabedateien

Die Eingabedateien werden nur gelesen. Gleiche Eingabe und gleiche Korrekturdatei ergeben
dieselben Ausgabedateien; die Pipeline kann deshalb beliebig oft laufen.

Korrekturdatei: CSV-Datei mit den Spalten Bereich, Nummer, Feld und Entscheidung, zum Beispiel
die ausgefüllte Prüfliste. Zeilen ohne Entscheidung werden übersprungen.

Aufruf: python3 -I umwandeln.py <Zwischenspeicher> <Zielordner> [--stichtag JJJJ-MM-TT]
                                [--korrekturen <Datei>]
"""
import argparse
import collections
import csv
import datetime
import hashlib
import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import konfig  # noqa: E402

PLZ_AT = re.compile(r"(?:A-)?(\d{4})")
PLZ_DE = re.compile(r"(?:D-)?(\d{5})")

# Felder, die die Korrekturdatei ändern darf: Bereich -> Feldname auf Deutsch -> Feld im Datensatz
KORRIGIERBAR = {
    "Kunde": {"Name": "name", "Chinesischer Name": "x_name_zh", "Nummer": "ref", "Land": "country",
              "Postleitzahl": "zip", "Ort": "city", "Straße": "street", "Telefon": "phone"},
    "Lieferant": {"Name": "name", "Land": "country", "Postleitzahl": "zip", "Ort": "city",
                  "Straße": "street", "Telefon": "phone"},
    "Artikel": {"Name": "name", "Chinesischer Name": "name_zh", "Einheit": "uom", "Gewicht": "weight",
                "Verkaufspreis": "list_price", "Einkaufspreis": "standard_price"},
}
ZAHLENFELDER = {"weight", "list_price", "standard_price"}
NICHT_UEBERNEHMEN = "nicht übernehmen"


# ---------------------------------------------------------------- Hilfsfunktionen

def lade(ordner, name):
    with open(os.path.join(ordner, f"{name}.csv"), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def text(wert):
    """Text ohne Leerzeichen am Anfang und Ende; leerer Text wird None."""
    wert = (wert or "").strip()
    return wert or None


def zahl(wert):
    """Zahl aus dem Zwischenspeicher; ein leeres Feld gilt als 0."""
    return Decimal(wert) if wert else Decimal(0)


def datum(wert):
    return datetime.date.fromisoformat(wert)


def normiert(wert):
    """Für Vergleiche: Kleinbuchstaben, ohne Leer- und Satzzeichen."""
    return re.sub(r"[\W_]", "", (wert or "").lower())


def kennung(art, nummer):
    """Externe Kennung im Zielsystem, z. B. zzf_kunde_1234. Über sie findet ein späterer Lauf
    denselben Datensatz wieder und ändert ihn, statt ihn ein zweites Mal anzulegen."""
    return f"zzf_{art}_" + re.sub(r"[^0-9A-Za-z]", "_", nummer)


def herkunft(r):
    return f"{r['_datei']}:{r['_satz']}"


def land_und_plz(plz):
    """R6: Land aus der Form der Postleitzahl. Vierstellig -> Österreich, fünfstellig ->
    Deutschland; ein vorangestelltes A- oder D- wird entfernt. Sonst bleibt das Land offen."""
    plz = text(plz)
    if plz is None:
        return None, None
    for muster, land in ((PLZ_AT, konfig.LAND_OESTERREICH), (PLZ_DE, konfig.LAND_DEUTSCHLAND)):
        treffer = muster.fullmatch(plz)
        if treffer:
            return land, treffer.group(1)
    return None, plz


def sha256(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------- Prüfliste und Korrekturen

class Pruefliste:
    """Sammelt die Fälle, die die Geschäftsführung entscheidet (R6 bis R12)."""

    def __init__(self):
        self.faelle = []

    def fall(self, regel, bereich, nummer, bezeichnung, feld, vorlaeufig, frage):
        self.faelle.append({"Regel": regel, "Bereich": bereich, "Nummer": nummer,
                            "Bezeichnung": bezeichnung or "", "Feld": feld,
                            "Vorläufig": "" if vorlaeufig is None else str(vorlaeufig),
                            "Frage": frage, "Entscheidung": "", "Stand": "offen"})


def lade_korrekturen(pfad):
    """Liest die Korrekturdatei: (Bereich, Nummer, Feld) -> Entscheidung."""
    korrekturen = {}
    if not pfad:
        return korrekturen
    with open(pfad, encoding="utf-8-sig", newline="") as f:
        for zeile, r in enumerate(csv.DictReader(f), start=2):
            entscheidung = text(r.get("Entscheidung"))
            if entscheidung is None:
                continue
            bereich, nummer, feld = text(r.get("Bereich")), text(r.get("Nummer")), text(r.get("Feld"))
            if bereich not in KORRIGIERBAR:
                raise ValueError(f"Korrekturdatei Zeile {zeile}: unbekannter Bereich {bereich!r}")
            if feld not in KORRIGIERBAR[bereich] and feld not in ("Übernehmen", "Dublette"):
                raise ValueError(f"Korrekturdatei Zeile {zeile}: Feld {feld!r} ist nicht änderbar")
            korrekturen[(bereich, nummer, feld)] = (entscheidung, zeile)
    return korrekturen


def wende_korrekturen_an(korrekturen, bestand, pruefliste):
    """Überträgt die Entscheidungen der Geschäftsführung in die Datensätze.

    bestand: Bereich -> {Nummer -> Datensatz}. Gibt die Korrekturen zurück, zu denen kein
    Datensatz gefunden wurde."""
    einheiten = set(konfig.EINHEITEN.values()) | {konfig.EINHEIT_ERSATZ}
    ohne_datensatz = []
    for (bereich, nummer, feld), (entscheidung, zeile) in sorted(korrekturen.items()):
        if feld == "Dublette":
            gruppe = [n.strip() for n in nummer.split("/")]
            if any(n not in bestand[bereich] for n in gruppe):
                ohne_datensatz.append(zeile)
                continue
            if entscheidung.lower() != "alle":
                if entscheidung not in gruppe:
                    raise ValueError(f"Korrekturdatei Zeile {zeile}: {entscheidung!r} gehört nicht zur Gruppe")
                for n in gruppe:
                    if n != entscheidung:
                        bestand[bereich][n]["_uebernehmen"] = False
                        bestand[bereich][n]["_grund"] = f"Dublette von {entscheidung} (Korrekturdatei)"
            continue
        satz = bestand[bereich].get(nummer)
        if satz is None:
            ohne_datensatz.append(zeile)
            continue
        if feld == "Übernehmen" or entscheidung.lower() == NICHT_UEBERNEHMEN:
            if entscheidung.lower() in ("nein", NICHT_UEBERNEHMEN):
                satz["_uebernehmen"] = False
                satz["_grund"] = "nicht übernehmen laut Korrekturdatei"
            continue
        ziel = KORRIGIERBAR[bereich][feld]
        if ziel in ZAHLENFELDER:
            try:
                wert = Decimal(entscheidung.replace(",", "."))
            except InvalidOperation:
                raise ValueError(f"Korrekturdatei Zeile {zeile}: {entscheidung!r} ist keine Zahl") from None
            if wert < 0:
                raise ValueError(f"Korrekturdatei Zeile {zeile}: negative Zahl")
            satz[ziel] = str(wert)
        elif ziel == "uom":
            if entscheidung not in einheiten:
                raise ValueError(f"Korrekturdatei Zeile {zeile}: unbekannte Einheit {entscheidung!r}")
            satz[ziel] = entscheidung
        elif ziel == "country":
            if not re.fullmatch(r"[A-Z]{2}", entscheidung):
                raise ValueError(f"Korrekturdatei Zeile {zeile}: Land als Kürzel mit zwei Buchstaben angeben")
            satz[ziel] = entscheidung
        else:
            satz[ziel] = entscheidung
        satz["_regeln"].append("Korrektur")
    # Fälle der Prüfliste als entschieden kennzeichnen
    for fall in pruefliste.faelle:
        for feld in (fall["Feld"], "Übernehmen"):
            if (fall["Bereich"], fall["Nummer"], feld) in korrekturen:
                fall["Entscheidung"] = korrekturen[(fall["Bereich"], fall["Nummer"], feld)][0]
                fall["Stand"] = "entschieden"
    return ohne_datensatz


# ---------------------------------------------------------------- Umwandlung

def umwandeln(zwischen, ziel, stichtag=None, korrekturdatei=None):
    K, W, L = lade(zwischen, "KUNDEN"), lade(zwischen, "WAREN"), lade(zwischen, "LIEFER")
    LH, LD, FIFO = lade(zwischen, "LH"), lade(zwischen, "LD"), lade(zwischen, "FIFO")
    EH, ED = lade(zwischen, "EH"), lade(zwischen, "ED")
    korrekturen = lade_korrekturen(korrekturdatei)

    # Stichtag: ohne Angabe der Tag des letzten Lieferscheins. Aktiv bzw. verkauft ist, was in
    # den zwölf Monaten davor auf mindestens einem Lieferschein steht (Abschnitt 3.2).
    stichtag = stichtag or max(datum(r["LDATUM"]) for r in LH)
    ab = stichtag - datetime.timedelta(days=konfig.AKTIV_TAGE)
    LH_z = [r for r in LH if ab < datum(r["LDATUM"]) <= stichtag]
    LD_z = [r for r in LD if ab < datum(r["DATUM"]) <= stichtag]

    protokoll = []
    pruefliste = Pruefliste()
    regeln = collections.Counter()

    def protokolliere(tabelle, quelle, nummer, ergebnis, regel, grund):
        datei, _, satz = quelle.partition(":") if quelle else ("", "", "")
        protokoll.append({"tabelle": tabelle, "datei": datei, "satz": satz, "nummer": nummer or "",
                          "ergebnis": ergebnis, "regel": regel, "grund": grund})

    # ---------------- Lieferanten: alle übernehmen
    lieferanten = {}
    for r in L:
        nr = text(r["NUM"])
        land, plz = land_und_plz(r["ZIP"])
        satz = {"xid": kennung("lieferant", nr), "ref": nr, "name": text(r["WNAME"]),
                "street": text(r["ADDR"]), "zip": plz, "city": text(r["CITY"]), "country": land,
                "phone": text(r["TELE"]), "ansprechpartner": text(r["PERSON"]),
                "herkunft": herkunft(r), "_regeln": [], "_uebernehmen": True, "_grund": ""}
        if land:
            satz["_regeln"].append("R6")
        else:
            satz["_regeln"].append("R6 Prüfliste")
            pruefliste.fall("R6", "Lieferant", nr, satz["name"], "Land", None,
                            "Land aus der Postleitzahl nicht erkennbar: Land angeben (z. B. AT)")
        lieferanten[nr] = satz

    # ---------------- Kunden: aktive aus dem Stamm, dazu Kunden, die nur in Lieferscheinen stehen
    stamm_nummern = collections.Counter(text(r["NUM"]) for r in K)
    aktiv = {text(r["NUM"]) for r in LH_z if text(r["NUM"]) in stamm_nummern}

    # Vermerke zu einzelnen Belegen, die später in deren Protokollzeile stehen
    vermerk = {}  # Herkunft des Belegs -> (Regel, Grund)

    # R3: Lieferscheine ohne Kundennummer bleiben nur im Archiv
    for r in LH:
        if text(r["NUM"]) is None:
            regeln["R3"] += 1
            vermerk[herkunft(r)] = ("R3", "Lieferschein ohne Kundennummer")

    # R2: Kundennummern, die nur in Lieferscheinen stehen
    nur_ls = collections.defaultdict(list)
    for r in LH:
        nr = text(r["NUM"])
        if nr and nr not in stamm_nummern:
            nur_ls[nr].append(r)
    zuordnung, anzulegen = {}, {}
    for nr in sorted(nur_ls):
        im_zeitraum = [r for r in nur_ls[nr] if ab < datum(r["LDATUM"]) <= stichtag]
        if not im_zeitraum:
            for r in nur_ls[nr]:
                vermerk[herkunft(r)] = ("R2", "Kunde nur in Lieferscheinen, nicht aktiv: nicht angelegt")
            continue
        letzter = max(im_zeitraum, key=lambda r: (r["LDATUM"], r["ZEIT"], r["_datei"], int(r["_satz"])))
        # gleicher Kunde, wenn Nummer bis auf führende Nullen, Postleitzahl und Straße gleich sind
        treffer = {text(k["NUM"]) for k in K
                   if text(k["NUM"]).lstrip("0") == nr.lstrip("0")
                   and text(k["ZIP"]) == text(letzter["ZIP"])
                   and normiert(k["ADDR"]) == normiert(letzter["ADDR"])}
        if len(treffer) == 1:
            ziel_nr = treffer.pop()
            zuordnung[nr] = ziel_nr
            aktiv.add(ziel_nr)
            regeln["R2 zugeordnet"] += 1
            for r in nur_ls[nr]:
                vermerk[herkunft(r)] = ("R2", f"Kunde {ziel_nr} zugeordnet (Nummer bis auf führende Null, "
                                              "Adresse gleich)")
        else:
            anzulegen[nr] = letzter
            regeln["R2 angelegt"] += 1
            for r in nur_ls[nr]:
                vermerk[herkunft(r)] = ("R2", "Kunde nur in Lieferscheinen")

    def kunde(r, ref, quelle):
        land, plz = land_und_plz(r["ZIP"])
        satz = {"xid": kennung("kunde", ref), "ref": ref,
                "name": text(r["WNAME"]) or text(r["CNAME"]), "x_name_zh": text(r["CNAME"]),
                "street": text(r["ADDR"]), "street2": text(r["WNAME2"]), "zip": plz,
                "city": text(r["CITY"]), "country": land, "phone": text(r.get("TELE")),
                "vat": text(r["UID"]), "preisgruppe": int(zahl(r["PRGRP"])),
                "herkunft": quelle, "_regeln": [], "_uebernehmen": True, "_grund": "",
                "_dt_name": text(r["WNAME"])}
        if satz["name"] is None:
            satz["name"] = f"Kunde {ref}"
            satz["_regeln"].append("R9 Prüfliste")
            pruefliste.fall("R9", "Kunde", ref, None, "Name", satz["name"],
                            "Kunde ohne Namen: Namen angeben")
        if land:
            satz["_regeln"].append("R6")
        else:
            satz["_regeln"].append("R6 Prüfliste")
            pruefliste.fall("R6", "Kunde", ref, satz["name"], "Land", None,
                            "Land aus der Postleitzahl nicht erkennbar: Land angeben (z. B. AT)")
        return satz

    kunden = {}
    gesehen = collections.Counter()
    for r in K:
        nr = text(r["NUM"])
        if nr not in aktiv:
            protokolliere("KUNDEN", herkunft(r), nr, "nicht übernommen", "",
                          "kein Lieferschein in den zwölf Monaten vor dem Stichtag")
            continue
        gesehen[nr] += 1
        if gesehen[nr] == 1:
            kunden[nr] = kunde(r, nr, herkunft(r))
            continue
        # R7: weiterer Datensatz mit derselben Nummer erhält vorläufig die Endung -2, -3, ...
        ref = f"{nr}-{gesehen[nr]}"
        satz = kunde(r, ref, herkunft(r))
        satz["_regeln"].append("R7 Prüfliste")
        pruefliste.fall("R7", "Kunde", ref, satz["name"], "Nummer", ref,
                        f"Zwei Kunden mit der Nummer {nr}: richtige Nummer angeben oder „nicht übernehmen“")
        kunden[ref] = satz
    for nr_ls, nr in zuordnung.items():
        kunden[nr]["_regeln"].insert(0, "R2")
    for nr, r in anzulegen.items():
        satz = kunde(r, nr, herkunft(r))
        satz["_regeln"].insert(0, "R2")
        satz["_angelegt"] = True
        kunden[nr] = satz

    # R8: mögliche Dubletten – gleicher deutscher Name und gleiche Postleitzahl, verschiedene Nummern
    gruppen = collections.defaultdict(list)
    for ref, satz in kunden.items():
        if normiert(satz["_dt_name"]):
            gruppen[(normiert(satz["_dt_name"]), satz["zip"])].append(ref)
    for refs in sorted(gruppen.values()):
        # eine Gruppe aus Datensätzen derselben Nummer ist schon ein Fall von R7
        if len(refs) > 1 and len({ref.split("-")[0] for ref in refs}) > 1:
            nummern = " / ".join(sorted(refs))
            for ref in refs:
                kunden[ref]["_regeln"].append("R8 Prüfliste")
            pruefliste.fall("R8", "Kunde", nummern, kunden[refs[0]]["name"], "Dublette", "alle",
                            "Gleicher Name und gleiche PLZ: derselbe Kunde? „alle“ übernehmen "
                            "oder die eine Nummer angeben, die bleibt")

    # ---------------- Artikel: verkaufte aus dem Stamm
    stamm_artikel = {text(r["NR"]) for r in W}
    verkauft = {text(r["NR"]) for r in LD_z if text(r["NR"]) in stamm_artikel}
    preisgruppen = sorted({s["preisgruppe"] for s in kunden.values()})
    artikel = {}
    for r in W:
        nr = text(r["NR"])
        if nr not in verkauft:
            protokolliere("WAREN", herkunft(r), nr, "nicht übernommen", "",
                          "in den zwölf Monaten vor dem Stichtag nicht verkauft")
            continue
        name = text(r["BZ_D"]) or text(r["BZ_C"])
        satz = {"xid": kennung("artikel", nr), "default_code": nr, "name": name,
                "name_zh": text(r["BZ_C"]), "uom": None, "steuer": konfig.STEUER[text(r["MWST"])],
                "list_price": None, "standard_price": None, "weight": None,
                "location": konfig.LAGERBEREICH.get(text(r["LAG_NR"])),
                "gruppenpreise": {}, "herkunft": herkunft(r),
                "_regeln": [], "_uebernehmen": True, "_grund": ""}
        if name is None:
            satz["name"] = f"Artikel {nr}"
            satz["_regeln"].append("R9 Prüfliste")
            pruefliste.fall("R9", "Artikel", nr, None, "Name", satz["name"], "Artikel ohne Bezeichnung")
        # R1 und R12: Einheit
        eht = text(r["EHT"])
        if eht in konfig.EINHEITEN:
            satz["uom"] = konfig.EINHEITEN[eht]
            if eht not in konfig.EINHEITEN_GRUNDFORM:
                satz["_regeln"].append("R1")
                regeln["R1"] += 1
        else:
            satz["uom"] = konfig.EINHEIT_ERSATZ
            satz["_regeln"].append("R12 Prüfliste")
            frage = "Einheit fehlt" if eht is None else f"Einheit „{eht}“ unbekannt"
            pruefliste.fall("R12", "Artikel", nr, name, "Einheit", satz["uom"], f"{frage}: Einheit angeben")
        # R11: Verkaufspreis = Preis der Gruppe 0
        preis0 = zahl(r[konfig.PREISFELD.format(0)])
        satz["list_price"] = str(preis0)
        if preis0 == 0:
            satz["_regeln"].append("R11 Prüfliste")
            pruefliste.fall("R11", "Artikel", nr, name, "Verkaufspreis", "0",
                            "Kein Preis der Gruppe 0: Verkaufspreis angeben (0 ist erlaubt)")
        # R10: Gewicht
        gewicht = zahl(r["WEIGHT"])
        satz["weight"] = str(gewicht)
        if gewicht == 0:
            satz["_regeln"].append("R10 Prüfliste")
            pruefliste.fall("R10", "Artikel", nr, name, "Gewicht", "0", "Gewicht je Einheit in kg angeben")
        if zahl(r["EK_EURO"]) > 0:
            satz["standard_price"] = str(zahl(r["EK_EURO"]))
        # Preise der Gruppen mit aktiven Kunden (ohne Gruppe 0, die der Verkaufspreis ist)
        for g in preisgruppen:
            preis = zahl(r[konfig.PREISFELD.format(g)])
            if g != 0 and preis > 0:
                satz["gruppenpreise"][str(g)] = str(preis)
        artikel[nr] = satz

    # R4: Artikelnummern in Lieferscheinpositionen ohne Artikelstamm
    ohne_stamm = collections.Counter(text(r["NR"]) for r in LD if text(r["NR"]) not in stamm_artikel)
    regeln["R4"] = len(ohne_stamm)
    for r in LD:
        if text(r["NR"]) in ohne_stamm:
            vermerk[herkunft(r)] = ("R4", "Artikelnummer ohne Artikelstamm: Artikel nicht angelegt")
    # R5: Lagerposten nicht übernehmen, der Anfangsbestand kommt aus der Inventur
    for r in FIFO:
        regeln["R5"] += 1
        protokolliere("FIFO", herkunft(r), text(r["NR"]), "nicht übernommen", "R5",
                      "Bestand wird durch die Inventur ersetzt")

    # ---------------- Korrekturen der Geschäftsführung
    bestand = {"Kunde": kunden, "Lieferant": lieferanten, "Artikel": artikel}
    ohne_datensatz = wende_korrekturen_an(korrekturen, bestand, pruefliste)
    # eine geänderte Kundennummer ändert auch die externe Kennung
    for satz in kunden.values():
        satz["xid"] = kennung("kunde", satz["ref"])

    # ---------------- Protokoll: genau eine Zeile je Datensatz des Altsystems
    angelegt_aus = {}
    for bereich, tabelle, menge in (("Lieferant", "LIEFER", lieferanten), ("Kunde", "KUNDEN", kunden),
                                    ("Artikel", "WAREN", artikel)):
        for nummer, satz in menge.items():
            regel = ", ".join(satz["_regeln"])
            if satz.get("_angelegt"):  # steht in der Zeile des Lieferscheins, aus dem er stammt
                angelegt_aus[satz["herkunft"]] = (nummer, regel, satz["_uebernehmen"], satz["_grund"])
                continue
            if not satz["_uebernehmen"]:
                ergebnis, grund = "nicht übernommen", satz["_grund"]
            else:
                ergebnis, grund = "übernommen", ""
            protokolliere(tabelle, satz["herkunft"], nummer, ergebnis, regel, grund)
    for name, tabelle, schluessel in (("LH", LH, "NUM"), ("LD", LD, "NR"), ("EH", EH, "EINNR"), ("ED", ED, "NR")):
        for r in tabelle:
            regel, grund = vermerk.get(herkunft(r), ("", ""))
            ergebnis = "archiviert"
            if herkunft(r) in angelegt_aus:
                nummer, regel, uebernehmen, grund_k = angelegt_aus[herkunft(r)]
                ergebnis = "archiviert; Kunde angelegt" if uebernehmen else "archiviert; Kunde nicht angelegt"
                grund = "Kunde nur in Lieferscheinen; Daten aus diesem, dem letzten Lieferschein" + \
                    (f"; {grund_k}" if grund_k else "")
            protokolliere(name, herkunft(r), text(r[schluessel]), ergebnis, regel, grund)
    protokoll.sort(key=lambda z: (z["tabelle"], z["datei"], int(z["satz"] or 0)))

    # ---------------- Preislisten: eine je Preisgruppe mit Kunden, Einträge = Gruppenpreise
    def behalten(menge):
        return {k: v for k, v in menge.items() if v["_uebernehmen"]}

    kunden_neu, artikel_neu, lieferanten_neu = behalten(kunden), behalten(artikel), behalten(lieferanten)
    preislisten = []
    for g in sorted({s["preisgruppe"] for s in kunden_neu.values()}):
        eintraege = [{"artikel": s["xid"], "fixed_price": s["gruppenpreise"][str(g)]}
                     for s in sorted(artikel_neu.values(), key=lambda s: s["default_code"])
                     if str(g) in s["gruppenpreise"]]
        preislisten.append({"xid": kennung("preisliste", str(g)), "name": f"Preisgruppe {g}",
                            "eintraege": eintraege})
    for s in kunden_neu.values():
        s["pricelist"] = kennung("preisliste", str(s["preisgruppe"]))

    # ---------------- Ausgabe
    os.makedirs(ziel, exist_ok=True)

    def schreibe_json(name, daten):
        with open(os.path.join(ziel, name), "w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")

    def ohne_intern(menge, schluessel):
        return [{k: v for k, v in s.items() if not k.startswith("_")}
                for s in sorted(menge.values(), key=lambda s: s[schluessel])]

    schreibe_json("lieferanten.json", ohne_intern(lieferanten_neu, "ref"))
    schreibe_json("kunden.json", ohne_intern(kunden_neu, "ref"))
    schreibe_json("artikel.json", ohne_intern(artikel_neu, "default_code"))
    schreibe_json("preislisten.json", preislisten)

    with open(os.path.join(ziel, "protokoll.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["tabelle", "datei", "satz", "nummer", "ergebnis", "regel", "grund"])
        w.writeheader()
        w.writerows(protokoll)
    reihenfolge = {r: i for i, r in enumerate(["R6", "R7", "R8", "R9", "R10", "R11", "R12"])}
    pruefliste.faelle.sort(key=lambda f: (reihenfolge[f["Regel"]], f["Bereich"], f["Nummer"]))
    with open(os.path.join(ziel, "pruefliste.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Nr", "Regel", "Bereich", "Nummer", "Bezeichnung", "Feld",
                                          "Vorläufig", "Frage", "Entscheidung", "Stand"])
        w.writeheader()
        for nr, fall in enumerate(pruefliste.faelle, start=1):
            w.writerow({"Nr": nr, **fall})

    # R6 und R10 bis R12 zählen je Fall der Prüfliste bzw. je Datensatz mit Land aus der PLZ
    for fall in pruefliste.faelle:
        regeln[fall["Regel"] + " Prüfliste"] += 1
    regeln["R6 Land erkannt"] = sum(1 for m in (kunden, lieferanten) for s in m.values() if "R6" in s["_regeln"])
    eingabe = sorted(f for f in os.listdir(zwischen) if f.endswith(".csv"))
    zusammenfassung = {
        "stichtag": stichtag.isoformat(),
        "zeitraum_ab": (ab + datetime.timedelta(days=1)).isoformat(),
        "eingabe_sha256": {f: sha256(os.path.join(zwischen, f)) for f in eingabe},
        "korrekturdatei": os.path.basename(korrekturdatei) if korrekturdatei else None,
        "korrekturen_ohne_datensatz": ohne_datensatz,
        "kunden": {"stamm_datensaetze": len(K), "stamm_nummern": len(stamm_nummern),
                   "aktiv_nummern": len(aktiv), "uebernommen": len(kunden_neu),
                   "davon_angelegt_R2": sum(1 for s in kunden_neu.values() if s.get("_angelegt"))},
        "artikel": {"stamm": len(W), "verkauft": len(verkauft), "uebernommen": len(artikel_neu)},
        "lieferanten": {"stamm": len(L), "uebernommen": len(lieferanten_neu)},
        "preislisten": {p["name"]: len(p["eintraege"]) for p in preislisten},
        "preise_nicht_uebernommen": {
            str(g): sum(1 for r in W if text(r["NR"]) in verkauft and zahl(r[konfig.PREISFELD.format(g)]) > 0)
            for g in konfig.PREISGRUPPEN if g not in preisgruppen},
        "regeln": dict(sorted(regeln.items())),
        "pruefliste": {"faelle": len(pruefliste.faelle),
                       "offen": sum(1 for f in pruefliste.faelle if f["Stand"] == "offen"),
                       "entschieden": sum(1 for f in pruefliste.faelle if f["Stand"] == "entschieden")},
        "protokoll_zeilen": len(protokoll),
    }
    schreibe_json("zusammenfassung.json", zusammenfassung)
    return zusammenfassung


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("zwischenspeicher")
    p.add_argument("ziel")
    p.add_argument("--stichtag", type=datetime.date.fromisoformat)
    p.add_argument("--korrekturen")
    a = p.parse_args()
    print(json.dumps(umwandeln(a.zwischenspeicher, a.ziel, a.stichtag, a.korrekturen),
                     ensure_ascii=False, indent=1))
