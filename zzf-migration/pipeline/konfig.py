"""Feste Festlegungen der Migration (Abschnitte 3.4.1 und 3.4.2, Anhang C).

Alles, was die Geschäftsführung festgelegt oder bestätigt hat, steht hier an einer Stelle,
damit die übrigen Module keine Werte fest einprogrammieren.
"""

# Aktiv bzw. verkauft: mindestens ein Lieferschein in den zwölf Monaten vor dem Stichtag (Abschnitt 3.2)
AKTIV_TAGE = 365

# R1: 19 Schreibweisen -> 8 Einheiten (Tabelle C3, Bedeutung von der Geschäftsführung bestätigt)
EINHEITEN = {
    "Pa": "Packung", "pa": "Packung",
    "Kt": "Karton", "Knt": "Karton", "knt": "Karton",
    "Fl": "Flasche", "FL": "Flasche", "fl": "Flasche",
    "Do": "Dose",
    "Kue": "Kübel", "kue": "Kübel", "Kuebe": "Kübel", "kubel": "Kübel", "kul": "Kübel",
    "St": "Stück", "st": "Stück",
    "kg": "Kilogramm", "Kg": "Kilogramm",
    "Sa": "Sack",
}
# Schreibweisen, die schon der Einheit entsprechen (keine Änderung im Sinne von R1)
EINHEITEN_GRUNDFORM = {"Pa", "Kt", "Fl", "Do", "Kue", "St", "kg", "Sa"}
# R12: fehlt die Einheit, vorläufig Stück
EINHEIT_ERSATZ = "Stück"

# Steuerkennzeichen -> Steuersatz in Prozent (bestätigt durch Brutto/Netto der Lieferscheinsummen)
STEUER = {"A": 20, "B": 10}

# Lagerbereich -> Lagerort (von der Geschäftsführung bestätigt)
LAGERBEREICH = {"1": "Trockenlager", "2": "Tiefkühllager"}

# Preis der Gruppe n steht im Feld PR_EURO<n>
PREISFELD = "PR_EURO{}"
PREISGRUPPEN = range(10)

# R6: Land aus der Form der Postleitzahl
LAND_OESTERREICH = "AT"
LAND_DEUTSCHLAND = "DE"
