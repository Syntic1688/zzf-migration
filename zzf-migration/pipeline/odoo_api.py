"""Zugriff auf Odoo über die Programmierschnittstelle JSON-2 (ab Odoo 19).

Jeder Aufruf ist ein HTTP-Request POST /json/2/<Modell>/<Methode> mit einem API-Schlüssel.
Die Verbindungsdaten kommen aus Umgebungsvariablen, damit der Schlüssel nicht im Code steht:
ODOO_URL (z. B. http://localhost:8069), ODOO_DB (Datenbank), ODOO_KEY (API-Schlüssel).
"""
import json
import os
import urllib.error
import urllib.request


class OdooFehler(RuntimeError):
    pass


class Odoo:
    def __init__(self, url=None, datenbank=None, schluessel=None):
        self.url = (url or os.environ["ODOO_URL"]).rstrip("/")
        self.datenbank = datenbank or os.environ["ODOO_DB"]
        self.schluessel = schluessel or os.environ["ODOO_KEY"]
        # lokale Verbindung ohne Proxy
        self._oeffner = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def __call__(self, modell, methode, ids=None, **argumente):
        """Ruft modell.methode auf, z. B. odoo("res.partner", "search_read", domain=[], fields=["name"])."""
        inhalt = dict(argumente)
        if ids:
            inhalt["ids"] = list(ids)
        anfrage = urllib.request.Request(
            f"{self.url}/json/2/{modell}/{methode}",
            data=json.dumps(inhalt).encode("utf-8"),
            headers={"Authorization": f"bearer {self.schluessel}", "X-Odoo-Database": self.datenbank,
                     "Content-Type": "application/json; charset=utf-8", "User-Agent": "zzf-migration"},
            method="POST")
        try:
            with self._oeffner.open(anfrage, timeout=1800) as antwort:
                return json.loads(antwort.read())
        except urllib.error.HTTPError as fehler:
            text = fehler.read().decode("utf-8", "replace")
            try:
                text = json.loads(text).get("message", text)
            except ValueError:
                pass
            raise OdooFehler(f"{modell}.{methode}: HTTP {fehler.code}: {text}") from None

    def kennung(self, xid):
        """Datenbank-ID zu einer externen Kennung wie base.at oder __import__.zzf_kunde_1; None, wenn es sie nicht gibt."""
        modul, name = xid.split(".", 1)
        treffer = self("ir.model.data", "search_read", domain=[["module", "=", modul], ["name", "=", name]],
                       fields=["res_id"], limit=1)
        return treffer[0]["res_id"] if treffer else None
