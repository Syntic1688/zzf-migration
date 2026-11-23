"""Prüfwerkzeug, Teil 1: Altdaten unabhängig von der Pipeline lesen und Texte vergleichen.

Eigenes Leseprogramm für dBASE-III-Dateien: Es liefert die Felder als unveränderte Bytes, ohne
sie zu dekodieren. Verglichen wird in umgekehrter Richtung: Ein Text aus dem Zielsystem oder
dem Archiv gilt als gleich, wenn sich seine Zeichen der Reihe nach in die Bytes des Originals
übersetzen lassen, deutsche Sonderzeichen in Codepage 437 (ein Byte), chinesische Zeichen in
GB2312 (zwei Byte).
"""
import glob
import os
import struct

HALB_VON, HALB_BIS = 0xA1, 0xF7  # mögliche erste Byte eines GB2312-Zeichens


def lies_dbf(pfad):
    """Liefert (Felder, Datensätze); Felder = [(Name, Typ, Länge, Nachkommastellen)],
    Datensatz = (geloescht, {Feld: Bytes})."""
    with open(pfad, "rb") as f:
        daten = f.read()
    anzahl, kopf, laenge = struct.unpack_from("<IHH", daten, 4)
    felder, pos = [], 32
    while daten[pos] != 0x0D:
        name = daten[pos:pos + 11].split(b"\0")[0].decode("ascii")
        felder.append((name, chr(daten[pos + 11]), daten[pos + 16], daten[pos + 17]))
        pos += 32
    saetze = []
    for k in range(anzahl):
        satz = daten[kopf + k * laenge: kopf + (k + 1) * laenge]
        if len(satz) < laenge:
            break
        werte, p = {}, 1
        for name, _typ, n, _nk in felder:
            werte[name] = satz[p:p + n]
            p += n
        saetze.append((satz[:1] == b"*", werte))
    return felder, saetze


def lies_tabelle(ordner, muster):
    """Alle Monatsdateien eines Musters in Dateireihenfolge; jeder Satz mit Datei und Satznummer."""
    ergebnis, felder = [], None
    for pfad in sorted(glob.glob(os.path.join(ordner, muster))):
        f, saetze = lies_dbf(pfad)
        felder = felder or f
        for nr, (geloescht, werte) in enumerate(saetze, start=1):
            werte["_datei"], werte["_satz"], werte["_geloescht"] = os.path.basename(pfad), nr, geloescht
            ergebnis.append(werte)
    return felder, ergebnis


def roh(wert):
    """Bytes eines Textfeldes ohne Leerzeichen am Anfang und Ende."""
    return wert.strip(b" ")


def _moeglich(zeichen):
    """Mögliche Bytefolgen eines Zeichens im Zeichensatz des Altsystems."""
    if ord(zeichen) < 0x80:
        return [zeichen.encode("ascii")]
    folgen = []
    for zs in ("cp437", "gb2312"):
        try:
            folgen.append(zeichen.encode(zs))
        except UnicodeEncodeError:
            pass
    return folgen


def passt(text, original):
    """True, wenn text Zeichen für Zeichen den Bytes original entspricht."""
    def ab(i, j):
        if i == len(text):
            return j == len(original)
        return any(original.startswith(b, j) and ab(i + 1, j + len(b)) for b in _moeglich(text[i]))
    return ab(0, 0)


def vergleiche_text(text, original):
    """Vergleicht einen Text mit den Original-Bytes (ohne Leerzeichen an den Rändern).

    Ergebnis: "gleich", "gleich, halbes Zeichen" (das Original endet mit dem ersten Byte eines
    abgeschnittenen chinesischen Zeichens, das im Text fehlt) oder "ungleich"."""
    text = (text or "").strip(" ")
    original = roh(original)
    if text.isascii() and original.isascii():  # schneller Weg für reine ASCII-Texte
        return "gleich" if text.encode("ascii") == original else "ungleich"
    if passt(text, original):
        return "gleich"
    if (original and HALB_VON <= original[-1] <= HALB_BIS and any(ord(z) > 0x2E7F for z in text)
            and passt(text, original[:-1].rstrip(b" "))):
        return "gleich, halbes Zeichen"
    return "ungleich"
