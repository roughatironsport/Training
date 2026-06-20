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
    page = st.sidebar.radio(
        "Bereich", ["Training eintragen", "Auswertung", "Bearbeiten & Löschen"]
    )

    st.sidebar.caption("Beide Nutzer sehen alle Daten gemeinsam.")
    return date, page


# ---------------------------------------------------------------------------
# Seite 1: Eingabemaske
# ---------------------------------------------------------------------------
def _adjust_value(key: str, delta: float, options: list) -> None:
    """
    Callback für die +/−-Buttons: ändert den Wert eines Dropdowns um `delta`
    und rastet auf den nächstgelegenen erlaubten Wert ein (klemmt automatisch
    an die Grenzen, da nur erlaubte Optionen gewählt werden).
    """
    current = st.session_state.get(key, options[0])
    target = current + delta
    st.session_state[key] = min(options, key=lambda o: abs(o - target))


def _delta_str(new_v: float, prev_v: float, unit: str, decimals: int) -> str:
    """Delta als absoluter Wert + Prozent, z. B. '+5.0 kg (+5.0%)'."""
    diff = new_v - prev_v
    pct = (diff / prev_v * 100) if prev_v else 0.0
    return f"{diff:+.{decimals}f} {unit} ({pct:+.1f}%)"


@st.dialog("📊 Dein Fortschritt")
def _progress_dialog(comparisons: list[dict], user: str, date_str: str) -> None:
    """Modales Fenster: Veränderung ggü. dem letzten Trainingstag je Übung."""
    st.caption(f"{user} · {date_str}")

    for comp in comparisons:
        new = comp["new"]
        prev = comp["prev"]
        st.markdown(f"#### {comp['exercise']}")

        if new is None:
            st.info("Nur Aufwärmsatz eingetragen – keine Arbeitssätze zum Auswerten.")
            continue
        if prev is None:
            st.success(
                "Erstes Mal mit Arbeitssätzen – Startwerte gesetzt! 💪  "
                f"Max {new['max_weight']:.1f} kg · Volumen {new['volume']:.0f} kg · "
                f"≈1RM {new['best_1rm']:.1f} kg"
            )
            continue

        st.caption(f"Vergleich mit {comp['prev_date']}")
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Max-Gewicht", f"{new['max_weight']:.1f} kg",
            delta=_delta_str(new["max_weight"], prev["max_weight"], "kg", 1),
        )
        c2.metric(
            "Volumen", f"{new['volume']:.0f} kg",
            delta=_delta_str(new["volume"], prev["volume"], "kg", 0),
        )
        c3.metric(
            "≈ 1RM", f"{new['best_1rm']:.1f} kg",
            delta=_delta_str(new["best_1rm"], prev["best_1rm"], "kg", 1),
        )

    # Gesamtfazit über alle vergleichbaren Übungen (Volumen).
    comparable = [c for c in comparisons if c["new"] and c["prev"]]
    if comparable:
        total_delta = sum(c["new"]["volume"] - c["prev"]["volume"] for c in comparable)
        st.divider()
        if total_delta > 0:
            st.success(f"Gesamtvolumen **+{total_delta:.0f} kg** gegenüber letztem Mal – stark! 🚀")
        elif total_delta < 0:
            st.warning(f"Gesamtvolumen **{total_delta:.0f} kg** – Deload oder leichter Tag? Dranbleiben! 💪")
        else:
            st.info("Gleiches Gesamtvolumen wie letztes Mal – konstant! 👊")

    if st.button("Schließen", type="primary"):
        st.rerun()


def render_input_page(user: str, date: dt.date) -> None:
    st.header("Training eintragen")
    st.caption(
        f"Nutzer: **{user}**  ·  Datum: **{date.isoformat()}**  ·  "
        "Pro Übung 1 Aufwärmsatz + 3 Arbeitssätze."
    )

    # Historie des Nutzers laden -> Felder mit den letzten Werten vorbelegen.
    try:
        history = db.fetch_trainings(user)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Historie konnte nicht geladen werden: {exc}")
        history = []
    defaults = logic.input_defaults(history, user)
    last_dates = logic.last_session_dates(history)

    # Hinweis: KEIN st.form, damit die +/−-Buttons sofort wirken können.
    exercise_inputs: dict[str, list[tuple[float, int]]] = {}

    for exercise in logic.EXERCISES:
        st.subheader(exercise)
        # Punkt 4: Hinweis, was beim letzten Mal trainiert wurde.
        if exercise in last_dates:
            st.caption(f"📅 Vorbelegt mit den Werten vom letzten Training: **{last_dates[exercise]}**")
        else:
            st.caption("📅 Noch kein vorheriges Training – Startwerte vorbelegt.")
        # Vier Spalten -> vier Sätze nebeneinander.
        cols = st.columns(4)
        sets: list[tuple[float, int]] = []

        for i, (col, (set_type, label)) in enumerate(zip(cols, logic.SET_LAYOUT)):
            # Vorbelegung aus dem letzten Trainingstag (sonst statische Defaults).
            default_w, default_r = defaults[exercise][i]
            w_key = f"{exercise}_{label}_w"
            r_key = f"{exercise}_{label}_r"
            with col:
                st.markdown(f"**{label}**")

                # --- Gewicht: Dropdown + Schnell-Buttons ---
                weight = st.selectbox(
                    "Gewicht (kg)",
                    logic.WEIGHT_OPTIONS,
                    index=logic.WEIGHT_OPTIONS.index(default_w),
                    format_func=lambda w: f"{w:g} kg",
                    key=w_key,
                )
                bw_minus, bw_plus = st.columns(2)
                bw_minus.button(
                    "−2,5", key=f"{w_key}_minus", use_container_width=True,
                    on_click=_adjust_value, args=(w_key, -2.5, logic.WEIGHT_OPTIONS),
                )
                bw_plus.button(
                    "+2,5", key=f"{w_key}_plus", use_container_width=True,
                    on_click=_adjust_value, args=(w_key, 2.5, logic.WEIGHT_OPTIONS),
                )

                # --- Wiederholungen: Dropdown + Schnell-Buttons ---
                reps = st.selectbox(
                    "Wdh.",
                    logic.REP_OPTIONS,
                    index=logic.REP_OPTIONS.index(default_r),
                    key=r_key,
                )
                br_minus, br_plus = st.columns(2)
                br_minus.button(
                    "−1", key=f"{r_key}_minus", use_container_width=True,
                    on_click=_adjust_value, args=(r_key, -1, logic.REP_OPTIONS),
                )
                br_plus.button(
                    "+1", key=f"{r_key}_plus", use_container_width=True,
                    on_click=_adjust_value, args=(r_key, 1, logic.REP_OPTIONS),
                )

                sets.append((weight, reps))

        exercise_inputs[exercise] = sets
        st.divider()

    submitted = st.button("💾 Speichern", type="primary")

    if submitted:
        documents = logic.build_set_documents(user, date.isoformat(), exercise_inputs)
        if not documents:
            st.warning(
                "Nichts gespeichert – bei allen Übungen war das Gewicht 0. "
                "Trage mindestens eine Übung mit Gewicht ein."
            )
            return

        # Vergleich gegen die Historie VOR dem Einfügen berechnen.
        comparisons = logic.build_comparisons(documents, history, date.isoformat())

        try:
            count = db.insert_training(documents)
        except Exception as exc:  # noqa: BLE001 – User soll Fehler sehen
            st.error(f"Speichern fehlgeschlagen: {exc}")
            return

        st.success(
            f"Gespeichert: {count} Übung(en) für {user} am {date.isoformat()}.",
            icon="✅",
        )
        # Fortschritts-Fenster öffnen.
        _progress_dialog(comparisons, user, date.isoformat())


# ---------------------------------------------------------------------------
# Seite 2: Dashboard / Auswertung
# ---------------------------------------------------------------------------
# Farbzuordnung für den gemeinsamen Kalender (muss zur Legende passen).
CAL_COLOR_A = "#1f77b4"     # nur User A (Patric) – blau
CAL_COLOR_B = "#ff7f0e"     # nur User B (Sandeep) – orange
CAL_COLOR_BOTH = "#2ca02c"  # beide – grün
CAL_COLOR_NONE = "#ebedf0"  # niemand – grau


def _combined_calendar_figure(cal: dict):
    """Gemeinsamer Trainingskalender beider Nutzer als Plotly-Heatmap."""
    # Diskrete Farbskala für die 4 Codes 0..3 (je Wert ein konstanter Block).
    colorscale = [
        [0.00, CAL_COLOR_NONE], [0.25, CAL_COLOR_NONE],
        [0.25, CAL_COLOR_A],    [0.50, CAL_COLOR_A],
        [0.50, CAL_COLOR_B],    [0.75, CAL_COLOR_B],
        [0.75, CAL_COLOR_BOTH], [1.00, CAL_COLOR_BOTH],
    ]
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
            zmax=3,
            colorscale=colorscale,
            showscale=False,
        )
    )
    fig.update_layout(
        height=max(180, 26 * len(cal["y_labels"]) + 50),
        margin=dict(l=10, r=10, t=20, b=10),
    )
    fig.update_xaxes(side="top", fixedrange=True)
    # Neueste Woche oben: y[0] (ältester Eintrag) nach unten -> Achse umkehren.
    fig.update_yaxes(fixedrange=True, autorange="reversed")
    return fig


def render_user_panel(user: str, df) -> None:
    """Rendert PRs + Verlaufs-Charts EINES Nutzers (für eine Spalte)."""
    st.subheader(user)

    if df.empty:
        st.info(f"Für **{user}** sind noch keine Trainings gespeichert.")
        return

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
        # st.table (server-seitig) statt st.dataframe -> kein dynamisches JS-Modul.
        st.table(pr_table.set_index("Übung"))

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
        sorted_table = table[show_cols].sort_values(
            ["Datum", "Übung"], ascending=[False, True]
        )
        # st.table statt st.dataframe -> umgeht das fehlschlagende JS-Modul.
        st.table(sorted_table.set_index(["Datum", "Übung", "Satz"]))


def _last_training_banner(user: str, df, today: dt.date) -> None:
    """Große, fette, ampelfarbene Anzeige: Zeit seit dem letzten Training."""
    days = logic.days_since_last_training(df, today)

    if days is None:
        color, text = "#888888", "noch kein Training"
    else:
        # Ampel: grün <=3 Tage, gelb <=5 Tage, sonst rot.
        if days <= 3:
            color = "#2ca02c"   # grün
        elif days <= 5:
            color = "#e0a800"   # gelb/amber
        else:
            color = "#d62728"   # rot

        if days == 0:
            text = "heute trainiert"
        elif days == 1:
            text = "vor 1 Tag"
        else:
            text = f"vor {days} Tagen"

    st.markdown(
        f"<div style='font-size:1.0rem;color:#666'>{user} – letztes Training</div>"
        f"<div style='font-size:2.3rem;font-weight:800;color:{color};line-height:1.1'>{text}</div>",
        unsafe_allow_html=True,
    )


def _render_stats(user: str, df) -> None:
    """Kennzahlen-Block (Einheiten + Pausen) für einen Nutzer."""
    st.markdown(f"**{user}**")
    stats = logic.rest_day_stats(df)
    c1, c2 = st.columns(2)
    c1.metric("Trainingseinheiten", stats["sessions"])
    c2.metric("Pausentage gesamt", stats["rest_days"])
    c3, c4 = st.columns(2)
    c3.metric("Ø Tage zwischen Einheiten", stats["avg_gap"])
    c4.metric("Längste Pause (Tage)", stats["longest_break"])


def render_dashboard() -> None:
    st.header("Auswertung – beide Nutzer im Vergleich")

    user_a, user_b = logic.USERS[0], logic.USERS[1]

    # Daten beider Nutzer einmal laden.
    try:
        df_a = logic.documents_to_dataframe(db.fetch_trainings(user_a))
        df_b = logic.documents_to_dataframe(db.fetch_trainings(user_b))
    except Exception as exc:  # noqa: BLE001
        st.error(f"Daten konnten nicht geladen werden: {exc}")
        return

    # --- Zeit seit letztem Training (auffällig, ampelfarben) ----------------
    today = dt.date.today()
    ban_left, ban_right = st.columns(2)
    with ban_left:
        _last_training_banner(user_a, df_a, today)
    with ban_right:
        _last_training_banner(user_b, df_b, today)

    st.divider()

    # --- Gemeinsamer Trainingskalender (volle Breite) ----------------------
    st.subheader("Gemeinsamer Trainingskalender")
    cal = logic.combined_calendar_matrix(
        {
            user_a: set(logic.training_dates(df_a)),
            user_b: set(logic.training_dates(df_b)),
        }
    )
    if cal is None:
        st.info("Noch keine Trainings vorhanden.")
    else:
        # Legende passend zu den Farben in _combined_calendar_figure.
        st.markdown(
            f"<span style='color:{CAL_COLOR_A}'>■</span> {user_a} &nbsp; "
            f"<span style='color:{CAL_COLOR_B}'>■</span> {user_b} &nbsp; "
            f"<span style='color:{CAL_COLOR_BOTH}'>■</span> beide &nbsp; "
            f"<span style='color:{CAL_COLOR_NONE}'>■</span> frei",
            unsafe_allow_html=True,
        )
        st.plotly_chart(_combined_calendar_figure(cal), use_container_width=True)

    # --- Statistik-Vergleich -----------------------------------------------
    st.subheader("Statistik")
    stat_left, stat_right = st.columns(2)
    with stat_left:
        _render_stats(user_a, df_a)
    with stat_right:
        _render_stats(user_b, df_b)

    st.divider()

    # --- Detail-Panels nebeneinander: links A (Patric), rechts B (Sandeep) -
    col_left, col_right = st.columns(2)
    with col_left:
        render_user_panel(user_a, df_a)
    with col_right:
        render_user_panel(user_b, df_b)


# ---------------------------------------------------------------------------
# Seite 3: Bearbeiten & Löschen
# ---------------------------------------------------------------------------
def render_manage_page(user: str) -> None:
    st.header("Bearbeiten & Löschen")
    st.caption(f"Eigene Einträge von **{user}** korrigieren oder entfernen.")

    try:
        documents = db.fetch_trainings(user)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Daten konnten nicht geladen werden: {exc}")
        return

    dates = logic.all_dates(documents)
    if not dates:
        st.info(f"Für **{user}** sind noch keine Trainings gespeichert.")
        return

    date = st.selectbox("Trainingstag wählen", dates)

    # --- Ganzen Trainingstag löschen ---------------------------------------
    with st.expander("⚠️ Ganzen Trainingstag löschen"):
        st.warning(f"Löscht ALLE Übungen von {user} am {date}.")
        confirm_day = st.checkbox("Ja, wirklich löschen", key=f"confirm_day_{date}")
        if st.button("🗑 Trainingstag löschen", disabled=not confirm_day, key=f"del_day_{date}"):
            n = db.delete_training_day(user, date)
            st.success(f"{n} Eintrag/Einträge vom {date} gelöscht.")
            st.rerun()

    st.divider()

    # --- Einzelne Übungen des Tages bearbeiten / löschen -------------------
    for doc in logic.docs_on_date(documents, date):
        exercise = doc["exercise"]
        stored = doc.get("sets", [])
        st.subheader(exercise)

        cols = st.columns(4)
        edited_sets: list[dict] = []
        for i, (col, (set_type, label)) in enumerate(zip(cols, logic.SET_LAYOUT)):
            if i < len(stored):
                w_def = logic._snap_to_option(float(stored[i].get("weight", 0)))
                r_def = min(15, max(0, int(stored[i].get("reps", 0))))
                stype = stored[i].get("type", set_type)
            else:
                w_def, r_def, stype = 0.0, 0, set_type

            w_key = f"edit_{date}_{exercise}_{label}_w"
            r_key = f"edit_{date}_{exercise}_{label}_r"
            with col:
                st.markdown(f"**{label}**")
                w = st.selectbox(
                    "Gewicht (kg)", logic.WEIGHT_OPTIONS,
                    index=logic.WEIGHT_OPTIONS.index(w_def),
                    format_func=lambda x: f"{x:g} kg", key=w_key,
                )
                bm, bp = st.columns(2)
                bm.button("−2,5", key=f"{w_key}_m", use_container_width=True,
                          on_click=_adjust_value, args=(w_key, -2.5, logic.WEIGHT_OPTIONS))
                bp.button("+2,5", key=f"{w_key}_p", use_container_width=True,
                          on_click=_adjust_value, args=(w_key, 2.5, logic.WEIGHT_OPTIONS))
                r = st.selectbox(
                    "Wdh.", logic.REP_OPTIONS,
                    index=logic.REP_OPTIONS.index(r_def), key=r_key,
                )
                rm, rp = st.columns(2)
                rm.button("−1", key=f"{r_key}_m", use_container_width=True,
                          on_click=_adjust_value, args=(r_key, -1, logic.REP_OPTIONS))
                rp.button("+1", key=f"{r_key}_p", use_container_width=True,
                          on_click=_adjust_value, args=(r_key, 1, logic.REP_OPTIONS))
            edited_sets.append({"type": stype, "weight": float(w), "reps": int(r)})

        action_l, action_r = st.columns(2)
        if action_l.button("💾 Aktualisieren", key=f"upd_{date}_{exercise}", type="primary"):
            db.update_exercise(user, date, exercise, edited_sets)
            st.success(f"{exercise} am {date} aktualisiert.")
            st.rerun()
        with action_r:
            confirm_ex = st.checkbox("Löschen bestätigen", key=f"confirm_ex_{date}_{exercise}")
            if st.button("🗑 Übung löschen", key=f"del_ex_{date}_{exercise}", disabled=not confirm_ex):
                db.delete_exercise(user, date, exercise)
                st.success(f"{exercise} am {date} gelöscht.")
                st.rerun()

        st.divider()


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
    elif page == "Auswertung":
        render_dashboard()
    else:
        render_manage_page(user)


if __name__ == "__main__":
    main()
