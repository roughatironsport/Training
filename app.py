"""
app.py
------
Streamlit-Oberfläche für das gemeinsame Trainingstagebuch.

Aufbau:
- Sidebar: Verbindungsstatus, Nutzer- und Datumsauswahl, Seitennavigation.
- Hauptbereich: entweder die Eingabemaske ("Training eintragen") oder
  das Dashboard ("Auswertung").

Die App teilt sich klar auf:
- db.py     -> MongoDB
- logic.py  -> Berechnungen
- app.py    -> UI (diese Datei)
"""

import datetime as dt

import pandas as pd
import plotly.express as px
import streamlit as st

import auth
import db
import logic

# ---------------------------------------------------------------------------
# Grundkonfiguration der Seite
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Trainingstagebuch",
    page_icon="🏋️",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def render_sidebar(user: str) -> tuple[dt.date, str]:
    """Zeichnet die Sidebar und gibt (datum, seite) zurück."""
    st.sidebar.title("🏋️ Trainingstagebuch")

    # Verbindungsstatus aktiv prüfen, damit Fehler früh sichtbar sind.
    ok, msg = db.ping()
    if ok:
        st.sidebar.success(msg, icon="✅")
    else:
        st.sidebar.error(msg, icon="⚠️")

    st.sidebar.divider()

    # Eingeloggter Nutzer + Logout (Identität kommt aus dem Login).
    st.sidebar.markdown(f"Angemeldet als **{user}**")
    auth.logout_button()

    st.sidebar.divider()

    date = st.sidebar.date_input("Datum", value=dt.date.today())

    st.sidebar.divider()
    page = st.sidebar.radio("Bereich", ["Training eintragen", "Auswertung"])

    st.sidebar.caption("Beide Nutzer sehen alle Daten gemeinsam.")
    return date, page


# ---------------------------------------------------------------------------
# Seite 1: Eingabemaske
# ---------------------------------------------------------------------------
def render_input_page(user: str, date: dt.date) -> None:
    st.header("Training eintragen")
    st.caption(
        f"Nutzer: **{user}**  ·  Datum: **{date.isoformat()}**  ·  "
        "Pro Übung 1 Aufwärmsatz + 3 Arbeitssätze."
    )

    # Das gesamte Formular wird gesammelt abgeschickt (ein Rerun statt vieler).
    with st.form("training_form", clear_on_submit=False):
        exercise_inputs: dict[str, list[tuple[float, int]]] = {}

        for exercise in logic.EXERCISES:
            st.subheader(exercise)
            # Vier Spalten -> vier Sätze nebeneinander.
            cols = st.columns(4)
            sets: list[tuple[float, int]] = []

            for col, (set_type, label) in zip(cols, logic.SET_LAYOUT):
                with col:
                    st.markdown(f"**{label}**")
                    weight = st.number_input(
                        "Gewicht (kg)",
                        min_value=0.0,
                        step=2.5,
                        key=f"{exercise}_{label}_w",
                    )
                    reps = st.number_input(
                        "Wdh.",
                        min_value=0,
                        step=1,
                        # Aufwärmsatz typ. mehr Reps, Arbeitssätze ~5 als Default.
                        value=8 if set_type == "warmup" else 5,
                        key=f"{exercise}_{label}_r",
                    )
                    sets.append((weight, reps))

            exercise_inputs[exercise] = sets
            st.divider()

        submitted = st.form_submit_button("💾 Speichern", type="primary")

    if submitted:
        documents = logic.build_set_documents(user, date.isoformat(), exercise_inputs)
        if not documents:
            st.warning(
                "Nichts gespeichert – bei allen Übungen war das Gewicht 0. "
                "Trage mindestens eine Übung mit Gewicht ein."
            )
            return
        try:
            count = db.insert_training(documents)
        except Exception as exc:  # noqa: BLE001 – User soll Fehler sehen
            st.error(f"Speichern fehlgeschlagen: {exc}")
            return

        st.success(
            f"Gespeichert: {count} Übung(en) für {user} am {date.isoformat()}.",
            icon="✅",
        )
        st.balloons()


# ---------------------------------------------------------------------------
# Seite 2: Dashboard / Auswertung
# ---------------------------------------------------------------------------
def render_dashboard(default_user: str) -> None:
    st.header("Auswertung")

    # Gemeinsames Tagebuch: man kann die Auswertung jedes Nutzers ansehen.
    # Default ist der eingeloggte Nutzer.
    user = st.radio(
        "Wessen Auswertung?",
        logic.USERS,
        index=logic.USERS.index(default_user),
        horizontal=True,
    )
    st.subheader(f"Daten von {user}")

    try:
        documents = db.fetch_trainings(user)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Daten konnten nicht geladen werden: {exc}")
        return

    df = logic.documents_to_dataframe(documents)

    if df.empty:
        st.info(
            f"Für **{user}** sind noch keine Trainings gespeichert. "
            "Lege links unter „Training eintragen“ los."
        )
        return

    # --- Kennzahlen / PRs ---------------------------------------------------
    st.subheader("Persönliche Bestleistungen")
    prs = logic.personal_records(df)
    # Pro Übung eine Spalte mit Max-Gewicht + geschätztem 1RM.
    cols = st.columns(len(logic.EXERCISES))
    pr_lookup = prs.set_index("exercise")
    for col, exercise in zip(cols, logic.EXERCISES):
        with col:
            if exercise in pr_lookup.index:
                row = pr_lookup.loc[exercise]
                st.metric(
                    label=f"{exercise} – Max",
                    value=f"{row['max_weight']:.1f} kg",
                    help=f"Geschätztes 1RM (Epley): {row['best_1rm']:.1f} kg",
                )
                st.caption(f"≈ 1RM: {row['best_1rm']:.1f} kg")
            else:
                st.metric(label=f"{exercise} – Max", value="–")

    st.divider()

    # --- Charts -------------------------------------------------------------
    tab_weight, tab_1rm, tab_volume = st.tabs(
        ["📈 Gewichtsentwicklung", "🔝 1RM-Verlauf (Epley)", "📊 Volumen pro Einheit"]
    )

    with tab_weight:
        prog = logic.progression_per_exercise(df)
        if prog.empty:
            st.info("Keine Arbeitssätze vorhanden.")
        else:
            fig = px.line(
                prog,
                x="date",
                y="max_weight",
                color="exercise",
                markers=True,
                labels={
                    "date": "Datum",
                    "max_weight": "Max. Arbeitsgewicht (kg)",
                    "exercise": "Übung",
                },
                title="Maximales Arbeitsgewicht über Zeit",
            )
            st.plotly_chart(fig, use_container_width=True)

    with tab_1rm:
        rm = logic.best_1rm_per_exercise(df)
        if rm.empty:
            st.info("Keine Arbeitssätze vorhanden.")
        else:
            fig = px.line(
                rm,
                x="date",
                y="best_1rm",
                color="exercise",
                markers=True,
                labels={
                    "date": "Datum",
                    "best_1rm": "Geschätztes 1RM (kg)",
                    "exercise": "Übung",
                },
                title="Geschätztes 1RM über Zeit (Epley)",
            )
            st.plotly_chart(fig, use_container_width=True)

    with tab_volume:
        vol = logic.volume_per_session(df)
        if vol.empty:
            st.info("Keine Arbeitssätze vorhanden.")
        else:
            fig = px.bar(
                vol,
                x="date",
                y="volume",
                labels={"date": "Datum", "volume": "Volumen (kg)"},
                title="Gesamtvolumen pro Trainingseinheit (Gewicht × Wdh.)",
            )
            st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # --- Rohdaten-Tabelle ---------------------------------------------------
    st.subheader("Alle Sätze")
    table = df.copy()
    # Datum hübsch als reines Datum (ohne Uhrzeit) darstellen.
    table["date"] = table["date"].dt.date
    table = table.rename(
        columns={
            "date": "Datum",
            "user": "Nutzer",
            "exercise": "Übung",
            "set_label": "Satz",
            "weight": "Gewicht (kg)",
            "reps": "Wdh.",
            "volume": "Volumen",
            "est_1rm": "≈ 1RM",
        }
    )
    show_cols = ["Datum", "Übung", "Satz", "Gewicht (kg)", "Wdh.", "Volumen", "≈ 1RM"]
    st.dataframe(
        table[show_cols].sort_values(["Datum", "Übung"], ascending=[False, True]),
        use_container_width=True,
        hide_index=True,
    )


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------
def main() -> None:
    # Login vorschalten – ohne gültigen Account geht es nicht weiter.
    user = auth.require_login()
    if not user:
        st.stop()

    date, page = render_sidebar(user)

    if page == "Training eintragen":
        render_input_page(user, date)
    else:
        render_dashboard(user)


if __name__ == "__main__":
    main()
