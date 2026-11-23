"""Lesen von dBASE-III-Tabellen (DBF) des Altsystems und Dekodieren der Texte.

Die Texte des Altsystems mischen zwei Zeichensätze im selben Feld:
- chinesische Zeichen im Zeichensatz GB2312 (zwei Byte, beide Byte 0xA1-0xFE, erstes Byte bis 0xF7),
  wie ihn die chinesische Systemerweiterung UCDOS verwendet,
- deutsche Umlaute und Sonderzeichen in Codepage 437 (ein Byte, z. B. 0x81 = ü, 0x84 = ä, 0xE1 = ß).

dekodiere() liest ein Byte-Paar nur dann als chinesisches Zeichen, wenn es im GB2312-Bereich liegt;
jedes andere Byte über 0x7F wird als Codepage 437 gelesen. Ein einzelnes GB2312-Lead-Byte am Feldende
(abgeschnittenes Zeichen) wird verworfen und gezählt.
"""
import datetime
import struct

CP437 = "cp437"


def dekodiere(raw: bytes):
    """Gibt (text, abgeschnitten) zurück; abgeschnitten = True, wenn am Ende ein halbes Zeichen stand."""
    out = []
    raw = raw.rstrip(b" ")
    i, n = 0, len(raw)
    abgeschnitten = False
    chinesisch = False
    while i < n:
        b = raw[i]
        if b < 0x80:
            out.append(chr(b))
            i += 1
            continue
        if 0xA1 <= b <= 0xF7 and i + 1 < n and 0xA1 <= raw[i + 1] <= 0xFE:
            try:
                out.append(raw[i:i + 2].decode("gb2312"))
                chinesisch = True
                i += 2
                continue
            except UnicodeDecodeError:
                pass
        if 0xA1 <= b <= 0xF7 and i == n - 1 and chinesisch:
            # letztes Byte eines chinesischen Textes ohne zweites Byte: halbes Zeichen
            # (entsteht, wenn eine Bezeichnung beim Speichern mitten im Zeichen abgeschnitten wurde)
            abgeschnitten = True
            break
        out.append(bytes([b]).decode(CP437))
        i += 1
    return "".join(out), abgeschnitten


def dekodiere_gbk(raw: bytes) -> str:
    """Einheitliche GBK-Dekodierung (zum Vergleich: so lesen Standardwerkzeuge die Texte)."""
    return raw.decode("gbk", errors="replace")


class Tabelle:
    def __init__(self, pfad):
        self.pfad = pfad
        with open(pfad, "rb") as f:
            self.daten = f.read()
        kopf = self.daten[:32]
        self.version = kopf[0]
        self.jahr, self.monat, self.tag = 1900 + kopf[1], kopf[2], kopf[3]
        self.anzahl, self.kopflaenge, self.satzlaenge = struct.unpack("<IHH", kopf[4:12])
        self.zeichensatz_byte = kopf[29]
        self.felder = []
        pos = 32
        while self.daten[pos] != 0x0D:
            fd = self.daten[pos:pos + 32]
            name = fd[:11].split(b"\x00")[0].decode("ascii")
            typ = chr(fd[11])
            laenge, nachkomma = fd[16], fd[17]
            self.felder.append((name, typ, laenge, nachkomma))
            pos += 32

    def roh(self):
        """Liefert (geloescht, {feld: bytes}) je Datensatz."""
        for k in range(self.anzahl):
            start = self.kopflaenge + k * self.satzlaenge
            satz = self.daten[start:start + self.satzlaenge]
            if not satz:
                break
            geloescht = satz[0:1] == b"*"
            pos = 1
            werte = {}
            for name, typ, laenge, nk in self.felder:
                werte[name] = satz[pos:pos + laenge]
                pos += laenge
            yield geloescht, werte

    def saetze(self):
        """Liefert dekodierte Datensätze als dict (Text, Zahl, Datum, Wahrheitswert)."""
        typen = {name: (typ, nk) for name, typ, laenge, nk in self.felder}
        for geloescht, werte in self.roh():
            d = {"_geloescht": geloescht}
            for name, raw in werte.items():
                typ, nk = typen[name]
                if typ == "C":
                    text, _ = dekodiere(raw)
                    d[name] = text.rstrip()
                elif typ == "N":
                    s = raw.decode("ascii").strip()
                    d[name] = (float(s) if nk else int(s)) if s else None
                elif typ == "D":
                    s = raw.decode("ascii").strip()
                    d[name] = datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8])) if s else None
                elif typ == "L":
                    d[name] = raw in (b"T", b"t", b"Y", b"y")
                else:
                    d[name] = raw
            yield d
