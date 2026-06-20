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

import plotly.express as px
import plotly.graph_objects as go
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
def _calendar_figure(cal: dict):
    """Baut aus logic.calendar_matrix(...) eine kalenderartige Plotly-Heatmap."""
    fig = go.Figure(
        go.Heatmap(
            z=cal["z"],
            x=cal["x_labels"],
            y=cal["y_labels"],
            text=cal["text"],
            hoverinfo="text",
            xgap=3,
            ygap=3,
            zmin=0,
            zmax=1,
            colorscale=[[0, "#ebedf0"], [1, "#216e39"]],  # grau -> grün
            showscale=False,
        )
    )
    # Höhe an Anzahl Wochen koppeln, damit Zellen quadratisch wirken.
    fig.update_layout(
        height=max(160, 26 * len(cal["y_labels"]) + 50),
        margin=dict(l=10, r=10, t=20, b=10),
    )
    fig.update_xaxes(side="top", fixedrange=True)
    # Neueste Woche oben: y[0] (ältester Eintrag) nach unten -> Achse umkehren.
    fig.update_yaxes(fixedrange=True, autorange="reversed")
    return fig


def render_user_panel(user: str) -> None:
    """Rendert die komplette Auswertung EINES Nutzers (für eine Spalte)."""
    st.subheader(user)

    try:
        documents = db.fetch_trainings(user)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Daten konnten nicht geladen werden: {exc}")
        return

    df = logic.documents_to_dataframe(documents)

    if df.empty:
        st.info(f"Für **{user}** sind noch keine Trainings gespeichert.")
        return

    # --- Trainingshäufigkeit -----------------------------------------------
    st.metric("Trainingseinheiten gesamt", logic.training_count(df))
    cal = logic.calendar_matrix(df)
    if cal:
        st.caption("Trainingskalender (grün = trainiert)")
        st.plotly_chart(_calendar_figure(cal), use_container_width=True)

    # --- Persönliche Bestleistungen ----------------------------------------
    prs = logic.personal_records(df)
    if not prs.empty:
        st.caption("Persönliche Bestleistungen")
        pr_table = prs.rename(
            columns={
                "exercise": "Übung",
                "max_weight": "Max (kg)",
                "best_1rm": "≈ 1RM (kg)",
            }
        )
        st.dataframe(pr_table, hide_index=True, use_container_width=True)

    # --- Verlaufs-Charts in Tabs -------------------------------------------
    tab_weight, tab_1rm, tab_volume = st.tabs(["📈 Gewicht", "🔝 1RM", "📊 Volumen"])

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
                labels={"date": "Datum", "max_weight": "Max. Gewicht (kg)", "exercise": "Übung"},
            )
            fig.update_layout(legend=dict(orientation="h", y=-0.3), margin=dict(t=10))
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
                labels={"date": "Datum", "best_1rm": "≈ 1RM (kg)", "exercise": "Übung"},
            )
            fig.update_layout(legend=dict(orientation="h", y=-0.3), margin=dict(t=10))
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
            )
            fig.update_layout(margin=dict(t=10))
            st.plotly_chart(fig, use_container_width=True)

    # --- Rohdaten (eingeklappt, damit die Spalte schlank bleibt) -----------
    with st.expander("Alle Sätze anzeigen"):
        table = df.copy()
        table["date"] = table["date"].dt.date
        table = table.rename(
            columns={
                "date": "Datum",
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


def render_dashboard() -> None:
    st.header("Auswertung – beide Nutzer im Vergleich")

    # Immer beide nebeneinander: links USERS[0] (Patric), rechts USERS[1] (Sandeep).
    col_left, col_right = st.columns(2)
    with col_left:
        render_user_panel(logic.USERS[0])
    with col_right:
        render_user_panel(logic.USERS[1])


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
        render_dashboard()


if __name__ == "__main__":
    main()
