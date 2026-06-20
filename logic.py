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

# Deutsche Anzeigenamen der Übungen (für Blöcke/Tooltips).
EXERCISE_DISPLAY = {
    "Deadlift": "Kreuzheben",
    "Bench Press": "Bankdrücken",
    "Squat": "Kniebeuge",
}

# Satz-Layout pro Übung: 1 Aufwärmsatz + 3 Arbeitssätze.
SET_LAYOUT = [
    ("warmup", "Aufwärmsatz"),
    ("work", "Arbeitssatz 1"),
    ("work", "Arbeitssatz 2"),
    ("work", "Arbeitssatz 3"),
]
# Reihenfolge der Satz-Labels (für sortierte Darstellung).
SET_LABELS = [label for _type, label in SET_LAYOUT]

# Auswahlwerte für die Eingabe-Dropdowns.
# Gewicht in 2,5-kg-Schritten von 0 bis 300 kg.
WEIGHT_OPTIONS = [round(i * 2.5, 1) for i in range(0, 121)]
# Wiederholungen ganzzahlig von 0 bis 15.
REP_OPTIONS = list(range(0, 16))

# Vorbelegung der ARBEITSSATZ-Gewichte je Nutzer und Übung (in kg).
# Der Aufwärmsatz wird automatisch auf die Hälfte gesetzt (siehe default_weight).
WEIGHT_DEFAULTS = {
    "Patric":  {"Deadlift": 200, "Bench Press": 120, "Squat": 100},
    "Sandeep": {"Deadlift": 150, "Bench Press": 80,  "Squat": 90},
}


def _snap_to_option(value: float) -> float:
    """Rundet einen Wert auf den nächstgelegenen erlaubten Gewichtswert."""
    return min(WEIGHT_OPTIONS, key=lambda w: abs(w - value))


def default_weight(user: str, exercise: str, set_type: str) -> float:
    """
    Liefert das Default-Gewicht für ein Dropdown – passend zu Nutzer, Übung
    und Satztyp. Arbeitssatz = hinterlegter Wert, Aufwärmsatz = die Hälfte
    (auf 2,5 kg gerundet). Fällt auf 0 zurück, wenn nichts hinterlegt ist.
    """
    base = WEIGHT_DEFAULTS.get(user, {}).get(exercise, 0)
    if set_type == "warmup":
        base = base * 0.5
    return _snap_to_option(base)


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


def last_session_sets(documents: list[dict]) -> dict:
    """
    Die zuletzt gespeicherten Sätze je Übung (vom jeweils jüngsten
    Trainingstag dieser Übung).

    Returns:
        {exercise: [ {"type","weight","reps"}, ... ]}
    """
    latest: dict[str, tuple[str, list]] = {}  # exercise -> (date_str, sets)
    for doc in documents:
        ex = doc.get("exercise")
        date = doc.get("date", "")
        # "YYYY-MM-DD" lässt sich lexikografisch vergleichen.
        if ex not in latest or date > latest[ex][0]:
            latest[ex] = (date, doc.get("sets", []))
    return {ex: sets for ex, (_date, sets) in latest.items()}


def last_session_dates(documents: list[dict]) -> dict:
    """Datum des letzten Trainingstags je Übung: {exercise: 'YYYY-MM-DD'}."""
    latest: dict[str, str] = {}
    for doc in documents:
        ex = doc.get("exercise")
        date = doc.get("date", "")
        if ex not in latest or date > latest[ex]:
            latest[ex] = date
    return latest


def all_dates(documents: list[dict]) -> list[str]:
    """Alle vorhandenen Trainingstage (Strings), neueste zuerst."""
    return sorted({doc.get("date", "") for doc in documents}, reverse=True)


def docs_on_date(documents: list[dict], date: str) -> list[dict]:
    """Alle Übungs-Dokumente eines bestimmten Tages."""
    return [doc for doc in documents if doc.get("date") == date]


def input_defaults(documents: list[dict], user: str) -> dict:
    """
    Vorbelegung der Eingabemaske: {exercise: [(weight, reps), ...] (4 Sätze)}.

    Nutzt die Sätze des letzten Trainingstags je Übung. Fehlt etwas, greifen
    die statischen Defaults (WEIGHT_DEFAULTS bzw. 8/5 Wdh.).
    """
    last_sets = last_session_sets(documents)
    result: dict[str, list[tuple[float, int]]] = {}

    for exercise in EXERCISES:
        prev = last_sets.get(exercise, [])
        sets: list[tuple[float, int]] = []
        for i, (set_type, _label) in enumerate(SET_LAYOUT):
            if i < len(prev):
                weight = _snap_to_option(float(prev[i].get("weight", 0)))
                reps = int(prev[i].get("reps", 0))
                # Sicherheitshalber in den erlaubten Bereich klemmen.
                reps = min(REP_OPTIONS[-1], max(REP_OPTIONS[0], reps))
            else:
                weight = default_weight(user, exercise, set_type)
                reps = 8 if set_type == "warmup" else 5
            sets.append((weight, reps))
        result[exercise] = sets
    return result


def session_metrics_from_sets(sets: list[dict]) -> dict | None:
    """
    Kennzahlen einer Übungseinheit aus ihren Sätzen (nur Arbeitssätze):
    max_weight, volume (Σ Gewicht×Wdh.), best_1rm. None, wenn keine Arbeitssätze.
    """
    work = [s for s in sets if s.get("type") == "work"]
    if not work:
        return None
    weights = [float(s.get("weight", 0)) for s in work]
    volume = sum(float(s.get("weight", 0)) * int(s.get("reps", 0)) for s in work)
    best_1rm = max(
        estimate_1rm(float(s.get("weight", 0)), int(s.get("reps", 0))) for s in work
    )
    return {"max_weight": max(weights), "volume": volume, "best_1rm": best_1rm}


def build_comparisons(new_docs: list[dict], history_docs: list[dict], new_date: str) -> list[dict]:
    """
    Vergleicht die gerade gespeicherten Übungen mit dem jeweils letzten
    früheren Trainingstag derselben Übung.

    Returns:
        Liste von dicts: {exercise, new, prev, prev_date}
        (new/prev sind Kennzahl-dicts oder None).
    """
    out = []
    for doc in new_docs:
        ex = doc["exercise"]
        new_metrics = session_metrics_from_sets(doc.get("sets", []))

        earlier = [
            d for d in history_docs
            if d.get("exercise") == ex and d.get("date", "") < new_date
        ]
        if earlier:
            last = max(earlier, key=lambda d: d["date"])
            prev_metrics = session_metrics_from_sets(last.get("sets", []))
            prev_date = last["date"]
        else:
            prev_metrics, prev_date = None, None

        out.append(
            {
                "exercise": ex,
                "new": new_metrics,
                "prev": prev_metrics,
                "prev_date": prev_date,
            }
        )
    return out


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


def training_dates(df: pd.DataFrame) -> list:
    """Sortierte Liste der unterschiedlichen Trainingstage (als Timestamps)."""
    if df.empty:
        return []
    return sorted(set(df["date"].dt.normalize()))


def days_since_last_training(df: pd.DataFrame, today) -> int | None:
    """
    Tage seit dem letzten Training. None, wenn noch kein Training existiert.

    Args:
        today: heutiges Datum (datetime.date).
    """
    dates = training_dates(df)
    if not dates:
        return None
    last_date = max(dates).date()  # Timestamp -> date
    return (today - last_date).days


def rest_day_stats(df: pd.DataFrame) -> dict:
    """
    Pausen-Statistik über den aktiven Zeitraum (erster bis letzter Trainingstag).

    Returns dict mit:
        sessions:      Anzahl Trainingseinheiten (= Trainingstage)
        rest_days:     Pausentage gesamt (Tage im Zeitraum ohne Training)
        avg_gap:       Ø Tage zwischen zwei Einheiten (z. B. 7.0 = wöchentlich)
        longest_break: längste Pause am Stück (Pausentage zwischen zwei Einheiten)
    """
    dates = training_dates(df)
    n = len(dates)
    if n <= 1:
        return {"sessions": n, "rest_days": 0, "avg_gap": 0.0, "longest_break": 0}

    # Abstände in Tagen zwischen aufeinanderfolgenden Einheiten.
    diffs = [(dates[i] - dates[i - 1]).days for i in range(1, n)]
    span_days = (dates[-1] - dates[0]).days + 1  # inkl. erstem und letztem Tag

    return {
        "sessions": n,
        "rest_days": span_days - n,           # Tage ohne Training im Zeitraum
        "avg_gap": round(sum(diffs) / len(diffs), 1),
        "longest_break": max(diffs) - 1,      # reine Pausentage am Stück
    }


def _format_sets(sets: list[dict]) -> str:
    """Sätze kompakt: gleiches Gewicht -> 'w×r,r,r', sonst 'w1×r1/w2×r2'."""
    if not sets:
        return ""
    weights = {float(s.get("weight", 0)) for s in sets}
    if len(weights) == 1:
        w = next(iter(weights))
        reps = ",".join(str(int(s.get("reps", 0))) for s in sets)
        return f"{w:g}×{reps}"
    return "/".join(
        f"{float(s.get('weight', 0)):g}×{int(s.get('reps', 0))}" for s in sets
    )


def day_summaries(documents: list[dict]) -> dict:
    """
    Leistungs-Zusammenfassung je Trainingstag (für den Kalender-Hover) –
    pro Übung eine Zeile (deutscher Name), Arbeitssätze + Aufwärmsatz.

    Returns:
        {date_str: "Kreuzheben: 200×5,5,5 · Aufw. 100×8<br>Bankdrücken: ..."}
    """
    by_date: dict[str, dict[str, str]] = {}
    for doc in documents:
        sets = doc.get("sets", [])
        work = [s for s in sets if s.get("type") == "work"]
        warm = [s for s in sets if s.get("type") == "warmup"]
        if not work and not warm:
            continue

        parts = []
        work_seg = _format_sets(work)
        if work_seg:
            parts.append(work_seg)
        warm_seg = _format_sets(warm)
        if warm_seg:
            parts.append(f"Aufw. {warm_seg}")

        name = EXERCISE_DISPLAY.get(doc["exercise"], doc["exercise"])
        by_date.setdefault(doc["date"], {})[doc["exercise"]] = f"{name}: " + " · ".join(parts)

    # Übungen in fester Reihenfolge (EXERCISES) ausgeben.
    result = {}
    for date, ex_map in by_date.items():
        lines = [ex_map[ex] for ex in EXERCISES if ex in ex_map]
        result[date] = "<br>".join(lines)
    return result


def combined_calendar_matrix(dates_by_user: dict, summaries_by_user: dict | None = None) -> dict | None:
    """
    Gemeinsamer Trainingskalender für beide Nutzer (vertikal, eine Zeile pro
    Kalenderwoche, Spalten Mo–So). Jeder Tag wird codiert, WER trainiert hat.

    Args:
        dates_by_user: {userA: set(Timestamps), userB: set(Timestamps)} –
                       Reihenfolge bestimmt die Farbzuordnung (A, B).

    Codierung in z:
        0 = niemand, 1 = nur userA, 2 = nur userB, 3 = beide

    Returns dict (z, y_labels, x_labels, text, users) oder None, wenn keine Daten.
    """
    users = list(dates_by_user.keys())
    set_a = dates_by_user[users[0]]
    set_b = dates_by_user[users[1]]
    all_days_trained = set_a | set_b
    if not all_days_trained:
        return None

    summaries_by_user = summaries_by_user or {}

    start = min(all_days_trained)
    end = max(all_days_trained)
    start_monday = start - pd.Timedelta(days=start.weekday())
    end_sunday = end + pd.Timedelta(days=6 - end.weekday())
    all_days = pd.date_range(start_monday, end_sunday, freq="D")

    z: list[list[int]] = []
    text: list[list[str]] = []
    y_labels: list[str] = []

    for i in range(0, len(all_days), 7):
        week = all_days[i : i + 7]
        z_row, t_row = [], []
        for day in week:
            in_a = day in set_a
            in_b = day in set_b
            code = 3 if (in_a and in_b) else (1 if in_a else (2 if in_b else 0))
            z_row.append(code)

            # Hover: Datum + pro Nutzer ein Block mit der Leistung (Übungszeilen).
            day_key = day.strftime("%Y-%m-%d")
            lines = [f"<b>📅 {day.strftime('%A, %d.%m.%Y')}</b>"]
            for u, hit in ((users[0], in_a), (users[1], in_b)):
                if hit:
                    summary = summaries_by_user.get(u, {}).get(day_key)
                    if summary:
                        lines.append(f"<b>{u}</b><br>{summary}")
                    else:
                        lines.append(f"<b>{u}</b>: trainiert")
            if len(lines) == 1:
                lines.append("— frei —")
            t_row.append("<br>".join(lines))
        z.append(z_row)
        text.append(t_row)

        # Trainingstage dieser Woche = Tage, an denen jemand trainiert hat.
        # Ab 2 Trainingstagen (Wochenziel) eine Rakete dahinter.
        day_count = sum(1 for c in z_row if c > 0)
        rocket = " 🚀" if day_count >= 2 else ""
        y_labels.append(f"{week[0].strftime('%d.%m.')} · {day_count}{rocket}")

    return {
        "z": z,
        "y_labels": y_labels,
        "x_labels": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
        "text": text,
        "users": users,
    }


def personal_records(df: pd.DataFrame) -> pd.DataFrame:
    """
    Persönliche Bestleistungen je Übung – immer ausgehend vom Satz mit dem
    HÖCHSTEN Arbeitsgewicht (bei Gleichstand der mit den meisten Wiederholungen).

    Spalten: exercise, max_weight, reps_at_max, best_1rm
    (best_1rm wird aus genau diesem Top-Satz nach Epley berechnet.)
    """
    ws = working_sets(df)
    if ws.empty:
        return pd.DataFrame(
            columns=["exercise", "max_weight", "reps_at_max", "best_1rm", "date"]
        )

    rows = []
    for exercise, group in ws.groupby("exercise"):
        # Höchstes Gewicht zuerst, bei Gleichstand die meisten Wiederholungen.
        top = group.sort_values(["weight", "reps"], ascending=False).iloc[0]
        weight = float(top["weight"])
        reps = int(top["reps"])
        rows.append(
            {
                "exercise": exercise,
                "max_weight": weight,
                "reps_at_max": reps,
                "best_1rm": estimate_1rm(weight, reps),
                "date": top["date"],  # wann der PR erzielt wurde
            }
        )
    return pd.DataFrame(rows)
