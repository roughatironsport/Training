# 🏋️ Trainingstagebuch (Streamlit + MongoDB)

Gemeinsames Trainingstagebuch für zwei Nutzer (**Patric** & **Sandeep**).
Beide sehen alle Daten und können Trainingseinträge hinzufügen.

Trainiert wird ein Ganzkörper-Programm mit **Deadlift**, **Bench Press** und
**Squat** – pro Übung 1 Aufwärmsatz + 3 Arbeitssätze.

## Projektstruktur

```
app.py        # Streamlit-UI (Sidebar, Eingabe, Dashboard)
db.py         # MongoDB-Anbindung (pymongo, st.secrets)
logic.py      # Berechnungen (Epley-1RM, Volumen, PRs, DataFrames)
requirements.txt
.streamlit/
  secrets.toml.example   # Vorlage -> nach secrets.toml kopieren
```

## Datenmodell (ein Dokument pro Übung & Tag)

```json
{
  "user": "Patric",
  "date": "2026-06-20",
  "exercise": "Squat",
  "sets": [
    {"type": "warmup", "weight": 60,  "reps": 8},
    {"type": "work",   "weight": 100, "reps": 5},
    {"type": "work",   "weight": 100, "reps": 5},
    {"type": "work",   "weight": 100, "reps": 5}
  ]
}
```

Eine Trainingseinheit erzeugt also bis zu 3 Dokumente (eines je Übung).

---

## Lokal starten

1. **Abhängigkeiten installieren**
   ```bash
   pip install -r requirements.txt
   ```

2. **Secrets anlegen**
   ```bash
   # Windows PowerShell
   Copy-Item .streamlit/secrets.toml.example .streamlit/secrets.toml
   ```
   Danach `.streamlit/secrets.toml` öffnen und echten Connection-String
   (mit DB-User + Passwort) eintragen.

3. **App starten**
   ```bash
   streamlit run app.py
   ```
   Die App öffnet sich unter <http://localhost:8501>.

> Alternativ ohne secrets.toml: Umgebungsvariable `MONGO_URI` setzen.

---

## MongoDB Atlas einrichten (Checkliste)

1. **Database User** anlegen: Atlas → *Database Access* → *Add New Database User*
   (Benutzername + Passwort merken – das kommt in den Connection-String).
2. **Network Access**: Atlas → *Network Access* → *Add IP Address*.
   Zum Testen `0.0.0.0/0` (von überall). Für Produktion lieber einschränken,
   für Streamlit Cloud aber meist `0.0.0.0/0` nötig (dynamische IPs).
3. **Connection-String** holen (*Connect* → *Drivers*). Wichtig: Die von Atlas
   gezeigte **Node.js**-Anleitung ignorieren – wir nutzen **Python/pymongo**.
   Der `mongodb+srv://...`-String passt aber für beide.

Datenbank (`training_diary`) und Collection (`trainings`) werden von Atlas
automatisch beim ersten Schreiben angelegt – nichts manuell nötig.

---

## Deployment auf Streamlit Community Cloud

1. Code in ein **GitHub-Repository** pushen
   (⚠️ ohne `.streamlit/secrets.toml` – die steht in `.gitignore`).
2. Auf <https://share.streamlit.io> einloggen → *New app* → Repo + `app.py` wählen.
3. **Secrets eintragen**: App → *Settings* → *Secrets* und dort einfügen:
   ```toml
   mongo_uri = "mongodb+srv://USER:PASSWORT@train.brex0oc.mongodb.net/?appName=train"
   ```
4. In Atlas *Network Access* sicherstellen, dass `0.0.0.0/0` freigegeben ist
   (Streamlit Cloud hat keine feste IP).
5. Deploy – fertig.

---

## Auswertungen im Dashboard

- **Gewichtsentwicklung** – max. Arbeitsgewicht pro Übung über Zeit
- **1RM-Verlauf (Epley)** – `1RM = Gewicht × (1 + Wdh./30)`
- **Volumen pro Einheit** – Summe aus Gewicht × Wdh. der Arbeitssätze
- **Persönliche Bestleistungen** – Max-Gewicht & bestes 1RM je Übung

Aufwärmsätze fließen bewusst **nicht** in die Fortschritts-Kennzahlen ein.
