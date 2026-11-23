# Migration eines DOS-Lagerverwaltungssystems nach Odoo

Quellcode zur Bachelorarbeit „Entwicklung und Validierung eines Migrationskonzepts für die Ablösung eines DOS-basierten Lagerverwaltungssystems in einem KMU“ von William Zhang, FH Technikum Wien, Studiengang Wirtschaftsinformatik, 2026.

Die Programme lesen die dBASE-Dateien des Altsystems, wandeln die Daten um, laden sie in Odoo und prüfen das Ergebnis mit einem getrennt programmierten Prüfwerkzeug. Die Abschnitte, Tabellen und Anhänge in den Kommentaren beziehen sich auf die Bachelorarbeit.

Die Programme sind in Python geschrieben und mit Unterstützung durch KI entstanden (Claude von Anthropic, siehe Abschnitt 2.3 der Arbeit).

## Keine Daten im Repository

Das Repository enthält nur Quellcode. Die Kopie der Altdaten, die Zwischenspeicher, die Importdateien, das Archiv und die Prüfberichte enthalten Kunden- und Lieferantendaten und sind deshalb nicht enthalten. Sie entstehen erst beim Aufruf der Programme. Die Datei `.gitignore` schließt sie aus.

Zugangsdaten stehen nicht im Code. Die Programme lesen sie beim Start aus Umgebungsvariablen.

| Variable | Bedeutung |
|---|---|
| `ODOO_URL` | Adresse der Odoo-Instanz, zum Beispiel `http://localhost:8069` |
| `ODOO_DB` | Name der Datenbank |
| `ODOO_KEY` | API-Schlüssel eines Benutzers |
| `ODOO_PASSWORT` | nur für `testfaelle.py`, Passwort für die Anmeldung wie in der Oberfläche |

## Aufbau

| Ordner und Datei | Aufgabe | Abschnitt der Arbeit |
|---|---|---|
| `pipeline/dbf.py` | Lesen der DBF-Dateien, Decoder für beide Zeichensätze (GB2312 und Codepage 437) | 3.1.2 |
| `export_csv.py` | Export der acht Datentabellen als CSV-Dateien | 3.1.2, Anhang G |
| `datenqualitaet/datenqualitaet.py` | Prüfung der Datenqualität am ganzen Bestand, nur Zählwerte | 3.1.4, Anhang B |
| `zielsystem/uebersetzungsgrad.py` | Anteil der übersetzten Oberflächentexte in Odoo 19 und ERPNext 16 | 3.3.3, Anhang A |
| `pipeline/lesen.py` | Schritt 1 der Pipeline, Lesen in den Zwischenspeicher | 3.4.3 |
| `pipeline/umwandeln.py` | Schritt 2, Auswahl, Zuordnung, Bereinigungsregeln R1 bis R12, Korrekturdatei | 3.4.1, 3.4.2, Anhang C |
| `pipeline/laden.py`, `pipeline/odoo_api.py` | Schritt 3, Laden über die Programmierschnittstelle von Odoo | 3.4.3 |
| `pipeline/archiv.py` | Schritt 4, Archiv der Belege mit Prüfsummen | 3.4.3 |
| `pipeline/lauf.py` | ein vollständiger Lauf aus den Schritten 1 bis 4 und der Prüfung | 3.4.3 |
| `pipeline/konfig.py` | Festlegungen der Geschäftsführung an einer Stelle | 3.4.1, 3.4.2 |
| `pipeline/einrichten.py` | Einrichten der Anpassungen in der Testinstanz | 3.3.4, 3.4.3 |
| `pipeline/lieferschein.xml` | Vorlage des zweisprachigen Lieferscheins | 3.3.4 |
| `pipeline/importdateien.py` | Importdateien 01 bis 11 für Odoo Online | 3.5.2 |
| `odoo_online/einrichtung_dateien.py` | Importdateien 12 und 13 für Lieferscheinvorlage und Bericht in Odoo Online | 3.5.2 |
| `testinstanz/import_test.py` | Probeimport der Importdateien in einer lokalen Odoo-Testinstanz, wie über die Oberfläche | 3.5.2 |
| `pruefliste/gewicht_aus_name.py` | Vorschlag für das Gewicht aus der Artikelbezeichnung | 3.4.2 |
| `pruefliste/korrekturdatei_aus_xlsx.py` | Korrekturdatei aus den Entscheidungen der Geschäftsführung | 3.4.2, 3.5.1 |
| `pruefwerkzeug/altdaten.py` | eigenes Leseprogramm des Prüfwerkzeugs, Rückvergleich der Texte | 3.4.3 |
| `pruefwerkzeug/pruefen.py` | Prüfwerkzeug für die Kennzahlen K1, K2a, K2b und die Stichprobe für K2c | 3.4.3, 3.5.1 |
| `pruefwerkzeug/testfaelle.py` | Testfälle der Kernprozesse für die Kennzahl K5 | 3.5.3 |

## Voraussetzungen

- Python 3.11 oder neuer
- `openpyxl` für `pruefliste/korrekturdatei_aus_xlsx.py` und `polib` für `zielsystem/uebersetzungsgrad.py` (`pip install -r requirements.txt`)
- für Laden, Prüfen und Testfälle eine Odoo-19-Instanz mit den Apps Verkauf, Lager und Einkauf, etwa die Community-Ausgabe lokal

Alle anderen Programme brauchen nur die Standardbibliothek von Python.

## Aufruf

Die Kopie des Altsystems ist der Ordner `HM9` mit den DBF-Dateien. Die Programme lesen ihn nur und verändern ihn nicht.

```bash
# Export der Altdaten als CSV-Dateien
python3 -I export_csv.py <HM9> <Zielordner>

# vollständiger Migrationslauf in die Testinstanz mit anschließender Prüfung
export ODOO_URL=http://localhost:8069 ODOO_DB=<Datenbank> ODOO_KEY=<API-Schlüssel>
python3 -I pipeline/einrichten.py
python3 -I pipeline/lauf.py <HM9> <Arbeitsordner> --stichtag JJJJ-MM-TT \
    --korrekturen <Korrekturdatei> --pruefwerkzeug pruefwerkzeug/pruefen.py

# Datenqualität der Kopie (gibt nur Zählwerte aus)
python3 -I datenqualitaet/datenqualitaet.py <HM9>

# Übersetzungsgrad (Quellcode von Odoo 19.0 und ERPNext version-16 von GitHub)
python3 -I zielsystem/uebersetzungsgrad.py <Odoo-Verzeichnis> <ERPNext-Verzeichnis>

# Probeimport in einer lokalen Testinstanz, läuft in der Odoo-Shell
IMPORT_DIR=<Ordner Importdateien> UMGEWANDELT=<Ordner umgewandelt> odoo-bin shell -d <Datenbank> < testinstanz/import_test.py

# Testfälle der Kernprozesse
python3 -I pruefwerkzeug/testfaelle.py <Ergebnisordner>

# Importdateien für Odoo Online (ohne Programmierschnittstelle)
python3 -I pipeline/umwandeln.py <Zwischenspeicher> <Ordner umgewandelt> --stichtag JJJJ-MM-TT
python3 -I pipeline/importdateien.py <Ordner umgewandelt> <Ordner Importdateien>
python3 -I odoo_online/einrichtung_dateien.py pipeline/lieferschein.xml <Ordner Importdateien>
```

Ohne `--stichtag` gilt der Tag des letzten Lieferscheins als Stichtag. Ein zweiter Lauf legt nichts doppelt an, weil jeder Datensatz eine feste externe Kennung trägt.

Die Messung des Übersetzungsgrads in der Arbeit beruht auf Odoo 19.0, Commit c09a7e5c (29.10.2026), und ERPNext version-16, Commit 9cd11b19 (28.10.2026).
