"""
logic.py
--------
Reine Berechnungs- und Aufbereitungslogik. Bewusst OHNE Streamlit- oder
MongoDB-Importe, damit dieser Teil unabhängig testbar bleibt.

Begriffe:
- Ein "Dokument" entspricht einer Übung an einem Tag mit ihren Sätzen
  (siehe Struktur in der App-Beschreibung).
- "Working Set" / type == "work" sind die Arbeitssätze; "warmup" wird für
  Fortschritts-Kennzahlen (1RM, Max, Volumen) bewusst NICHT berücksichtigt.
"""

import pandas as pd

# Feste Konfiguration – an einer Stelle, damit app.py darauf zugreifen kann.
USERS = ["Patric", "Sandeep"]
EXERCISES = ["Deadlift", "Bench Press", "Squat"]

# Satz-Layout pro Übung: 1 Aufwärmsatz + 3 Arbeitssätze.
SET_LAYOUT = [
    ("warmup", "Aufwärmsatz"),
    ("work", "Arbeitssatz 1"),
    ("work", "Arbeitssatz 2"),
    ("work", "Arbeitssatz 3"),
]


def estimate_1rm(weight: float, reps: int) -> float:
    """
    Schätzt das 1-Rep-Maximum nach der Epley-Formel:

        1RM = weight * (1 + reps / 30)

    Bei reps == 1 ergibt das ziemlich genau das Gewicht selbst.
    Gibt 0 zurück, wenn keine sinnvollen Werte vorliegen.
    """
    if weight <= 0 or reps <= 0:
        return 0.0
    return round(weight * (1 + reps / 30), 1)


def build_set_documents(user: str, date_str: str, exercise_inputs: dict) -> list[dict]:
    """
    Baut aus den Formular-Eingaben die zu speichernden MongoDB-Dokumente.

    Args:
        user: Nutzername.
        date_str: Datum als "YYYY-MM-DD".
        exercise_inputs: {
            "Squat": [(weight, reps), (weight, reps), ...],  # 4 Tupel
            ...
        }

    Returns:
        Liste von Dokumenten (eines pro Übung) im vorgegebenen Schema.
        Übungen, bei denen alle Gewichte 0 sind, werden übersprungen.
    """
    documents = []
    for exercise, sets in exercise_inputs.items():
        # Übung überspringen, wenn nichts Sinnvolles eingetragen wurde.
        if all(weight <= 0 for weight, _ in sets):
            continue

        set_docs = []
        for (set_type, _label), (weight, reps) in zip(SET_LAYOUT, sets):
            set_docs.append(
                {
                    "type": set_type,
                    "weight": float(weight),
                    "reps": int(reps),
                }
            )

        documents.append(
            {
                "user": user,
                "date": date_str,
                "exercise": exercise,
                "sets": set_docs,
            }
        )
    return documents


def documents_to_dataframe(documents: list[dict]) -> pd.DataFrame:
    """
    Flacht die verschachtelten Dokumente in ein "langes" DataFrame ab –
    eine Zeile pro Satz. Grundlage für alle Tabellen und Charts.

    Spalten: date, user, exercise, set_type, set_label, weight, reps,
             volume, est_1rm
    """
    rows = []
    for doc in documents:
        # Pro Dokument sauber durchnummerieren, damit Labels stabil sind.
        work_counter = 0
        for s in doc.get("sets", []):
            set_type = s.get("type", "work")
            if set_type == "warmup":
                set_label = "Aufwärmsatz"
            else:
                work_counter += 1
                set_label = f"Arbeitssatz {work_counter}"

            weight = float(s.get("weight", 0))
            reps = int(s.get("reps", 0))
            rows.append(
                {
                    "date": doc["date"],
                    "user": doc["user"],
                    "exercise": doc["exercise"],
                    "set_type": set_type,
                    "set_label": set_label,
                    "weight": weight,
                    "reps": reps,
                    "volume": weight * reps,
                    "est_1rm": estimate_1rm(weight, reps),
                }
            )

    df = pd.DataFrame(rows)
    if not df.empty:
        # Echtes Datum für korrekte Zeitachsen-Sortierung in Plotly.
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.sort_values("date")
    return df


def working_sets(df: pd.DataFrame) -> pd.DataFrame:
    """Filtert auf reine Arbeitssätze (ohne Aufwärmsätze)."""
    if df.empty:
        return df
    return df[df["set_type"] == "work"]


def progression_per_exercise(df: pd.DataFrame) -> pd.DataFrame:
    """
    Maximales Arbeitsgewicht pro Übung und Tag – Basis für die
    Gewichtsentwicklung über Zeit.

    Spalten: date, exercise, max_weight
    """
    ws = working_sets(df)
    if ws.empty:
        return pd.DataFrame(columns=["date", "exercise", "max_weight"])
    return (
        ws.groupby(["date", "exercise"], as_index=False)["weight"]
        .max()
        .rename(columns={"weight": "max_weight"})
        .sort_values("date")
    )


def best_1rm_per_exercise(df: pd.DataFrame) -> pd.DataFrame:
    """
    Bestes geschätztes 1RM pro Übung und Tag – Basis für den 1RM-Verlauf.

    Spalten: date, exercise, best_1rm
    """
    ws = working_sets(df)
    if ws.empty:
        return pd.DataFrame(columns=["date", "exercise", "best_1rm"])
    return (
        ws.groupby(["date", "exercise"], as_index=False)["est_1rm"]
        .max()
        .rename(columns={"est_1rm": "best_1rm"})
        .sort_values("date")
    )


def volume_per_session(df: pd.DataFrame) -> pd.DataFrame:
    """
    Gesamtvolumen (Gewicht × Reps, nur Arbeitssätze) pro Trainingstag.

    Spalten: date, volume
    """
    ws = working_sets(df)
    if ws.empty:
        return pd.DataFrame(columns=["date", "volume"])
    return (
        ws.groupby("date", as_index=False)["volume"]
        .sum()
        .sort_values("date")
    )


def training_count(df: pd.DataFrame) -> int:
    """Anzahl der Trainingseinheiten = Anzahl unterschiedlicher Trainingstage."""
    if df.empty:
        return 0
    return int(df["date"].dt.normalize().nunique())


def calendar_matrix(df: pd.DataFrame) -> dict | None:
    """
    Baut die Daten für eine kalenderartige Heatmap (GitHub-Stil, vertikal:
    eine Zeile pro Kalenderwoche, sieben Spalten Mo–So).

    Returns:
        dict mit
            z:        2D-Liste (0/1 – ob an dem Tag trainiert wurde)
            y_labels: Wochen-Labels (Datum des Montags), chronologisch
            x_labels: ["Mo", "Di", ... , "So"]
            text:     2D-Liste mit Hover-Text je Tag
        oder None, wenn keine Daten vorhanden sind.
    """
    if df.empty:
        return None

    trained_days = set(df["date"].dt.normalize())
    start = min(trained_days)
    end = max(trained_days)

    # Auf volle Wochen ausrichten: Montag vor dem ersten, Sonntag nach dem letzten Tag.
    start_monday = start - pd.Timedelta(days=start.weekday())
    end_sunday = end + pd.Timedelta(days=6 - end.weekday())
    all_days = pd.date_range(start_monday, end_sunday, freq="D")

    z: list[list[int]] = []
    text: list[list[str]] = []
    y_labels: list[str] = []

    # In 7er-Blöcke (Wochen) gruppieren.
    for i in range(0, len(all_days), 7):
        week = all_days[i : i + 7]
        z_row, t_row = [], []
        for day in week:
            trained = day in trained_days
            z_row.append(1 if trained else 0)
            mark = " · ✓ trainiert" if trained else ""
            t_row.append(f"{day.strftime('%a %d.%m.%Y')}{mark}")
        z.append(z_row)
        text.append(t_row)
        y_labels.append(week[0].strftime("%d.%m."))

    return {
        "z": z,
        "y_labels": y_labels,
        "x_labels": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
        "text": text,
    }


def personal_records(df: pd.DataFrame) -> pd.DataFrame:
    """
    Persönliche Bestleistungen je Übung: höchstes Arbeitsgewicht und
    bestes geschätztes 1RM. Für die Kennzahl-Kacheln im Dashboard.

    Spalten: exercise, max_weight, best_1rm
    """
    ws = working_sets(df)
    if ws.empty:
        return pd.DataFrame(columns=["exercise", "max_weight", "best_1rm"])
    return (
        ws.groupby("exercise", as_index=False)
        .agg(max_weight=("weight", "max"), best_1rm=("est_1rm", "max"))
    )
