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
# Globales Styling (Buttons, Metrik-Karten, Abstände) + Branding
# ---------------------------------------------------------------------------
def inject_css() -> None:
    """Einmaliges, additives CSS – rein kosmetisch, keine Funktionsänderung."""
    st.markdown(
        """
        <style>
          .block-container { padding-top: 2.0rem; max-width: 1250px; }
          h1, h2, h3 { letter-spacing: -0.01em; }
          hr { margin: 1.1rem 0; }

          /* Buttons: weiche Ecken, Hover-Feedback */
          .stButton > button {
            border-radius: 10px;
            font-weight: 600;
            transition: all .12s ease-in-out;
            border: 1px solid #d8dee9;
          }
          .stButton > button:hover {
            border-color: #2563eb;
            transform: translateY(-1px);
          }

          /* Metrik-Kacheln als Karten */
          div[data-testid="stMetric"] {
            background: #f8fafc;
            border: 1px solid #e6eaf0;
            border-radius: 12px;
            padding: 10px 14px;
          }
          div[data-testid="stMetricLabel"] { opacity: .75; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def app_banner(subtitle: str) -> None:
    """Dezentes Branding-Banner statt nacktem st.header."""
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:.6rem;
                    padding:.2rem 0 1rem;border-bottom:2px solid #eef1f5;margin-bottom:1.1rem">
          <span style="font-size:1.9rem">🏋️</span>
          <div>
            <div style="font-size:1.55rem;font-weight:800;line-height:1">Trainingstagebuch</div>
            <div style="font-size:.85rem;color:#64748b">{subtitle}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _style_fig(fig):
    """Einheitliches Plotly-Theming passend zum App-Look (Linien/Balken)."""
    fig.update_layout(
        template="plotly_white",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="sans-serif", size=13, color="#1f2933"),
        colorway=["#2563eb", "#ff7f0e", "#16a34a"],
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#eef1f5", zeroline=False)
    return fig


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def _sidebar_rest_days(days: int | None) -> None:
    """Große, ampelfarbene Anzeige der Pausentage seit dem letzten Training."""
    if days is None:
        color, big, sub = "#888888", "–", "noch kein Training"
    else:
        # Gleiche Ampel wie im Dashboard: grün <=3, gelb <=5, sonst rot.
        if days <= 3:
            color = "#2ca02c"
        elif days <= 5:
            color = "#e0a800"
        else:
            color = "#d62728"
        big = str(days)
        if days == 0:
            sub = "heute trainiert"
        elif days == 1:
            sub = "Pausentag"
        else:
            sub = "Pausentage"

    st.sidebar.markdown(
        "<div style='font-size:0.85rem;color:#666'>seit letztem Training</div>"
        f"<div style='font-size:2.8rem;font-weight:800;color:{color};line-height:1.0'>{big}</div>"
        f"<div style='font-size:0.95rem;font-weight:600;color:{color}'>{sub}</div>",
        unsafe_allow_html=True,
    )


def render_sidebar(user: str) -> str:
    """Zeichnet die Sidebar und gibt die gewählte Seite zurück."""
    st.sidebar.title("🏋️ Trainingstagebuch")

    # Verbindungsstatus dezent (grün nur als kurze Zeile, Fehler weiterhin auffällig).
    ok, msg = db.ping()
    if ok:
        st.sidebar.caption("🟢 Datenbank verbunden")
    else:
        st.sidebar.error(msg, icon="⚠️")

    st.sidebar.divider()

    # Eingeloggter Nutzer + Logout (Identität kommt aus dem Login).
    st.sidebar.markdown(f"Angemeldet als **{user}**")

    # Große, ampelfarbene Anzeige: Pausentage seit dem letzten Training.
    try:
        df_user = logic.documents_to_dataframe(db.fetch_trainings(user))
        days = logic.days_since_last_training(df_user, dt.date.today())
    except Exception:  # noqa: BLE001
        days = None
    _sidebar_rest_days(days)

    auth.logout_button()

    st.sidebar.divider()
    # Navigation als segmented_control (klarer Modus-Umschalter); None abfangen.
    pages = ["Training eintragen", "Auswertung", "Bearbeiten & Löschen"]
    page = st.sidebar.segmented_control(
        "Bereich", pages, default="Training eintragen", selection_mode="single"
    )
    if page is None:
        page = "Training eintragen"

    st.sidebar.caption("Beide Nutzer sehen alle Daten gemeinsam.")
    # Dezentes Wasserzeichen / Branding.
    st.sidebar.markdown(
        "<div style='margin-top:1.2rem;font-size:.72rem;color:#cbd5e1'>"
        "Trainingstagebuch · Patric &amp; Sandeep</div>",
        unsafe_allow_html=True,
    )
    return page


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


def _fmt_num(x: float) -> str:
    """Zahl auf 0,5 gerundet: ganzzahlig ohne Nachkommastelle, sonst mit .5."""
    rounded = round(x * 2) / 2
    return f"{int(rounded)}" if rounded == int(rounded) else f"{rounded:.1f}"


def _change_badge(current: float, previous) -> str:
    """
    Kleines farbiges Badge: grün ▲ wenn größer als letztes Mal, rot ▼ wenn
    kleiner, grau wenn gleich. Leerer String, wenn kein Vergleich möglich.
    """
    if previous is None:
        return "<span style='color:#bbb;font-size:0.8rem'>—</span>"
    diff = current - previous
    if diff > 0:
        return f"<span style='color:#2ca02c;font-weight:700;font-size:0.85rem'>▲ {diff:+g}</span>"
    if diff < 0:
        return f"<span style='color:#d62728;font-weight:700;font-size:0.85rem'>▼ {diff:+g}</span>"
    return "<span style='color:#999;font-size:0.8rem'>= gleich</span>"


def _pct_delta_str(values: list) -> str | None:
    """
    Prozentuale Änderung vom vorletzten zum letzten Wert (None bei < 2 Werten).
    st.metric stellt das Vorzeichen automatisch als grünen ↑ / roten ↓ Pfeil dar.
    """
    if len(values) < 2:
        return None
    prev, latest = float(values[-2]), float(values[-1])
    pct = (latest - prev) / prev * 100 if prev else 0.0
    return f"{pct:+.1f}%"


def _render_change_metrics(series_df, value_col: str, help_text: str) -> None:
    """
    Kachelreihe je Übung: aktueller Wert + %-Änderung zur vorigen Einheit
    (grüner ↑ / roter ↓ Pfeil via st.metric).
    """
    st.caption("Veränderung zur vorigen Einheit")
    exercises = list(series_df["exercise"].unique())
    cols = st.columns(len(exercises))
    for col, exercise in zip(cols, exercises):
        group = series_df[series_df["exercise"] == exercise].sort_values("date")
        values = list(group[value_col])
        col.metric(
            exercise,
            f"{_fmt_num(values[-1])} kg",
            delta=_pct_delta_str(values),
            help=help_text,
        )


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


def render_input_page(user: str) -> None:
    app_banner("Training eintragen")

    # Punkt 1: Datum hier oben wählen (nicht mehr in der Sidebar).
    date = st.date_input("Datum des Trainings", value=dt.date.today())

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
    last_sets = logic.last_session_sets(history)  # für Veränderungs-Badges

    # Punkt 4: Schon ein Training an diesem Tag? Dann Speichern sperren.
    existing_dates = {doc.get("date") for doc in history}
    already_logged = date.isoformat() in existing_dates
    if already_logged:
        st.warning(
            f"Für **{date.isoformat()}** existiert bereits ein Training. "
            "Änderungen bitte unter **Bearbeiten & Löschen** vornehmen.",
            icon="🔒",
        )

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

            # Werte des letzten Trainings für den Vergleich (Badges).
            prev_set = last_sets.get(exercise, [])
            prev_w = float(prev_set[i]["weight"]) if i < len(prev_set) else None
            prev_r = int(prev_set[i]["reps"]) if i < len(prev_set) else None

            with col:
                st.markdown(f"**{label}**")

                # --- Gewicht: Dropdown + Schnell-Buttons + Veränderungs-Badge ---
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
                st.markdown(_change_badge(weight, prev_w), unsafe_allow_html=True)

                # --- Wiederholungen: Dropdown + Schnell-Buttons + Badge ---
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
                st.markdown(_change_badge(reps, prev_r), unsafe_allow_html=True)

                sets.append((weight, reps))

        exercise_inputs[exercise] = sets
        st.divider()

    submitted = st.button(
        "💾 Speichern",
        type="primary",
        disabled=already_logged,
        help=(
            "Für diesen Tag existiert bereits ein Training – Änderungen unter "
            "„Bearbeiten & Löschen“."
            if already_logged
            else "Trainingstag speichern"
        ),
    )

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
# Planungszonen ab letztem Training (blass, damit klar von "trainiert" trennbar).
CAL_ZONE_GREEN = "#c7eccb"   # 1–3 Tage Pause
CAL_ZONE_YELLOW = "#fdeeba"  # 4–5 Tage Pause
CAL_ZONE_RED = "#f6c6c6"     # >5 Tage Pause

# Reihenfolge = Codes 0..6 (siehe logic.combined_calendar_matrix).
_CAL_COLORS = [
    CAL_COLOR_NONE, CAL_COLOR_A, CAL_COLOR_B, CAL_COLOR_BOTH,
    CAL_ZONE_GREEN, CAL_ZONE_YELLOW, CAL_ZONE_RED,
]


def _combined_calendar_figure(cal: dict):
    """Gemeinsamer Trainingskalender beider Nutzer als Plotly-Heatmap."""
    # Diskrete Farbskala für die 7 Codes 0..6 (je Wert ein konstanter Block).
    n = len(_CAL_COLORS)
    colorscale = []
    for idx, color in enumerate(_CAL_COLORS):
        colorscale.append([idx / n, color])
        colorscale.append([(idx + 1) / n, color])

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
            zmax=6,
            colorscale=colorscale,
            showscale=False,
        )
    )
    fig.update_layout(
        height=max(180, 26 * len(cal["y_labels"]) + 50),
        margin=dict(l=10, r=10, t=20, b=10),
        # Punkt 2: breiteres, schöneres Tooltip.
        hoverlabel=dict(
            bgcolor="white",
            bordercolor="#cccccc",
            font=dict(size=13, color="#222222"),
            align="left",
            namelength=-1,
        ),
    )
    fig.update_xaxes(side="top", fixedrange=True)
    # Neueste Woche oben: y[0] (ältester Eintrag) nach unten -> Achse umkehren.
    fig.update_yaxes(fixedrange=True, autorange="reversed")

    x_labels = cal["x_labels"]
    y_labels = cal["y_labels"]

    # Trainings-Icons in die Zellen: 1 Hantel bei einem Nutzer, 2 bei beiden.
    for r, row in enumerate(cal["z"]):
        for c, code in enumerate(row):
            if code in (1, 2):
                icon = "🏋️"
            elif code == 3:
                icon = "🏋️🏋️"
            else:
                continue
            fig.add_annotation(
                x=x_labels[c], y=y_labels[r], text=icon,
                showarrow=False, font=dict(size=12),
            )

    # Heutigen Tag immer markieren (Rahmen um die Zelle + Pin).
    today_xy = cal.get("today_xy")
    if today_xy is not None:
        tx, ty = today_xy
        c = x_labels.index(tx)
        r = y_labels.index(ty)
        fig.add_shape(
            type="rect",
            x0=c - 0.5, x1=c + 0.5, y0=r - 0.5, y1=r + 0.5,
            line=dict(color="#111827", width=2.5),
            fillcolor="rgba(0,0,0,0)",
            xref="x", yref="y", layer="above",
        )
        fig.add_annotation(
            x=tx, y=ty, text="heute", showarrow=False, yshift=-13,
            font=dict(size=9, color="#111827"),
        )
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
        st.markdown(
            "<span title='Bestes Gewicht = höchstes je Arbeitssatz bewegtes "
            "Gewicht (mit den dabei erreichten Wiederholungen). ≈ 1RM = daraus "
            "geschätztes 1-Wiederholungs-Maximum (Epley). Datum = wann erreicht.' "
            "style='cursor:help;font-weight:600'>Persönliche Bestleistungen ⓘ</span>",
            unsafe_allow_html=True,
        )
        today = dt.date.today()

        def _date_with_ago(ts) -> str:
            d = ts.date()
            days = (today - d).days
            if days == 0:
                ago = "heute"
            elif days == 1:
                ago = "vor 1 Tag"
            else:
                ago = f"vor {days} Tagen"
            return f"{d.strftime('%d.%m.%Y')} ({ago})"

        # Bestes Gewicht inkl. Wiederholungen; Zahlen auf 0,5 gerundet.
        pr_display = pd.DataFrame(
            {
                "Übung": prs["exercise"],
                "Bestes Gewicht": [
                    f"{_fmt_num(w)} kg × {r}"
                    for w, r in zip(prs["max_weight"], prs["reps_at_max"])
                ],
                "≈ 1RM (kg)": [_fmt_num(v) for v in prs["best_1rm"]],
                "Datum": [_date_with_ago(ts) for ts in prs["date"]],
            }
        )
        # st.table (server-seitig) statt st.dataframe -> kein dynamisches JS-Modul.
        st.table(pr_display.set_index("Übung"))

    # --- Verlaufs-Charts untereinander (keine Tabs mehr) -------------------
    st.markdown(
        "<h5 title='Höchstes Arbeitsgewicht je Trainingstag im Zeitverlauf "
        "(Aufwärmsätze zählen nicht).' style='cursor:help'>📈 Gewicht</h5>",
        unsafe_allow_html=True,
    )
    prog = logic.progression_per_exercise(df)
    if prog.empty:
        st.info("Keine Arbeitssätze vorhanden.")
    else:
        _render_change_metrics(
            prog, "max_weight",
            "Höchstes Arbeitsgewicht der letzten Einheit. Pfeil/Prozent = "
            "Änderung gegenüber der vorherigen Einheit dieser Übung.",
        )
        fig = px.line(
            prog, x="date", y="max_weight", color="exercise", markers=True,
            labels={"date": "Datum", "max_weight": "Max. Gewicht (kg)", "exercise": "Übung"},
        )
        fig.update_layout(legend=dict(orientation="h", y=-0.3), margin=dict(t=10))
        st.plotly_chart(_style_fig(fig), use_container_width=True)

    st.markdown(
        "<h5 title='Geschätztes 1-Wiederholungs-Maximum (Epley: Gewicht × "
        "(1 + Wdh./30)) je Trainingstag im Zeitverlauf.' style='cursor:help'>"
        "🔝 1RM (geschätzt)</h5>",
        unsafe_allow_html=True,
    )
    rm = logic.best_1rm_per_exercise(df)
    if rm.empty:
        st.info("Keine Arbeitssätze vorhanden.")
    else:
        _render_change_metrics(
            rm, "best_1rm",
            "Geschätztes 1-Wiederholungs-Maximum (Epley-Formel) der letzten "
            "Einheit. Pfeil/Prozent = Änderung gegenüber der vorherigen.",
        )
        fig = px.line(
            rm, x="date", y="best_1rm", color="exercise", markers=True,
            labels={"date": "Datum", "best_1rm": "≈ 1RM (kg)", "exercise": "Übung"},
        )
        fig.update_layout(legend=dict(orientation="h", y=-0.3), margin=dict(t=10))
        st.plotly_chart(_style_fig(fig), use_container_width=True)

    st.markdown(
        "<h5 title='Gesamtvolumen je Trainingstag = Summe aus Gewicht × "
        "Wiederholungen aller Arbeitssätze.' style='cursor:help'>📊 Volumen</h5>",
        unsafe_allow_html=True,
    )
    vol = logic.volume_per_session(df)
    if vol.empty:
        st.info("Keine Arbeitssätze vorhanden.")
    else:
        st.caption("Veränderung zur vorigen Einheit")
        vals = list(vol.sort_values("date")["volume"])
        st.metric(
            "Volumen letzte Einheit", f"{_fmt_num(vals[-1])} kg",
            delta=_pct_delta_str(vals),
            help="Gesamtvolumen = Summe aus Gewicht × Wiederholungen (nur Arbeitssätze).",
        )
        fig = px.bar(
            vol, x="date", y="volume",
            labels={"date": "Datum", "volume": "Volumen (kg)"},
        )
        fig.update_layout(margin=dict(t=10))
        st.plotly_chart(_style_fig(fig), use_container_width=True)

    # --- Rohdaten je Datum, in Blöcken pro Übung (eingeklappt) -------------
    with st.expander("Alle Sätze anzeigen"):
        dates = sorted(df["date"].dt.date.unique(), reverse=True)
        sel_date = st.selectbox(
            "Datum wählen",
            dates,
            format_func=lambda d: d.strftime("%d.%m.%Y"),
            key=f"alle_saetze_{user}",
        )
        day_df = df[df["date"].dt.date == sel_date]

        # Pro Übung ein Block; Übungen in fester Reihenfolge, Sätze sortiert.
        for exercise in logic.EXERCISES:
            ex_df = day_df[day_df["exercise"] == exercise]
            if ex_df.empty:
                continue
            # Sätze in definierter Reihenfolge (Aufwärmsatz, Arbeitssatz 1..3).
            ex_df = ex_df.copy()
            ex_df["_order"] = ex_df["set_label"].map(
                {lbl: i for i, lbl in enumerate(logic.SET_LABELS)}
            )
            ex_df = ex_df.sort_values("_order")

            name = logic.EXERCISE_DISPLAY.get(exercise, exercise)
            st.markdown(f"**🏋️ {name}**")
            block = pd.DataFrame(
                {
                    "Satz": ex_df["set_label"].values,
                    "Gewicht (kg)": [_fmt_num(x) for x in ex_df["weight"]],
                    "Wdh.": ex_df["reps"].astype(int).values,
                    "Volumen": [_fmt_num(x) for x in ex_df["volume"]],
                    "≈ 1RM": [_fmt_num(x) for x in ex_df["est_1rm"]],
                }
            )
            st.table(block.set_index("Satz"))


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

    # Volumen-Veränderung des letzten Trainings ggü. dem vorherigen.
    vol = logic.volume_per_session(df)
    vol_line = ""
    if len(vol) >= 2:
        vals = list(vol.sort_values("date")["volume"])
        prev, latest = vals[-2], vals[-1]
        pct = (latest - prev) / prev * 100 if prev else 0.0
        if pct > 0:
            vcolor, arrow = "#2ca02c", "▲"
        elif pct < 0:
            vcolor, arrow = "#d62728", "▼"
        else:
            vcolor, arrow = "#888888", "="
        vol_tip = (
            "Veränderung des Gesamtvolumens (Summe aus Gewicht × Wiederholungen "
            "aller Arbeitssätze) der letzten Trainingseinheit gegenüber der "
            "vorherigen. Positiv = mehr Gesamtbelastung."
        )
        vol_line = (
            f"<div title='{vol_tip}' style='font-size:1.0rem;font-weight:600;color:{vcolor};cursor:help'>"
            f"{arrow} {pct:+.1f}% Volumen ggü. vorherigem Training</div>"
        )
    elif len(vol) == 1:
        vol_line = "<div style='font-size:0.9rem;color:#999'>erstes Training – kein Vergleich</div>"

    time_tip = "Anzahl Tage seit dem letzten Trainingstag dieses Nutzers."
    st.markdown(
        f"<div style='font-size:1.0rem;color:#666'>{user} – letztes Training</div>"
        f"<div title='{time_tip}' style='font-size:2.3rem;font-weight:800;color:{color};line-height:1.1;cursor:help'>{text}</div>"
        f"{vol_line}",
        unsafe_allow_html=True,
    )


def _render_stats(user: str, df) -> None:
    """Kennzahlen-Block (Einheiten + Pausen) für einen Nutzer."""
    st.markdown(f"**{user}**")
    stats = logic.rest_day_stats(df)
    c1, c2 = st.columns(2)
    c1.metric("Trainingseinheiten", stats["sessions"], help="Anzahl unterschiedlicher Trainingstage.")
    c2.metric("Pausentage gesamt", stats["rest_days"], help="Tage ohne Training im aktiven Zeitraum.")
    c3, c4 = st.columns(2)
    c3.metric("Ø Tage zwischen Einheiten", stats["avg_gap"], help="Durchschnitt; 7 = wöchentlich.")
    c4.metric("Längste Pause (Tage)", stats["longest_break"], help="Größte Lücke am Stück.")


def render_dashboard() -> None:
    app_banner("Auswertung")

    user_a, user_b = logic.USERS[0], logic.USERS[1]

    # Daten beider Nutzer einmal laden (Rohdokumente + DataFrame).
    try:
        docs_a = db.fetch_trainings(user_a)
        docs_b = db.fetch_trainings(user_b)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Daten konnten nicht geladen werden: {exc}")
        return
    df_a = logic.documents_to_dataframe(docs_a)
    df_b = logic.documents_to_dataframe(docs_b)

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
        },
        summaries_by_user={
            user_a: logic.day_summaries(docs_a),
            user_b: logic.day_summaries(docs_b),
        },
        today=today,
    )
    if cal is None:
        st.info("Noch keine Trainings vorhanden.", icon="📭")
    else:
        # Legende mit Hover-Tooltips (title) je Eintrag.
        st.markdown(
            f"<span title='Tage, an denen nur {user_a} trainiert hat' style='cursor:help'>"
            f"<span style='color:{CAL_COLOR_A};font-size:1.1rem'>■</span> {user_a}</span> &nbsp; "
            f"<span title='Tage, an denen nur {user_b} trainiert hat' style='cursor:help'>"
            f"<span style='color:{CAL_COLOR_B};font-size:1.1rem'>■</span> {user_b}</span> &nbsp; "
            f"<span title='Tage, an denen beide am selben Tag trainiert haben' style='cursor:help'>"
            f"<span style='color:{CAL_COLOR_BOTH};font-size:1.1rem'>■</span> beide</span> &nbsp;&nbsp; "
            f"<b>Planung ab letztem Training:</b> &nbsp;"
            f"<span title='3–5 Tage Pause: ideales Zeitfenster fürs nächste Training' style='cursor:help'>"
            f"<span style='color:{CAL_ZONE_GREEN};font-size:1.1rem'>■</span> ideal (3–5 T.)</span> &nbsp; "
            f"<span title='2 Tage (fast bereit) bzw. 6–7 Tage (langsam wieder Zeit)' style='cursor:help'>"
            f"<span style='color:{CAL_ZONE_YELLOW};font-size:1.1rem'>■</span> Übergang (2 / 6–7 T.)</span> &nbsp; "
            f"<span title='1 Tag (zu früh, Regeneration) bzw. ab 8 Tagen (überfällig)' style='cursor:help'>"
            f"<span style='color:{CAL_ZONE_RED};font-size:1.1rem'>■</span> zu früh / überfällig (1 / 8+ T.)</span>",
            unsafe_allow_html=True,
        )
        st.caption(
            "Eine Zeile = eine Woche. Zahl hinter dem Datum = Trainingstage der Woche, "
            "🚀 ab 2. 🏋️ = trainiert (🏋️🏋️ = beide). Schwarzer Rahmen = heute. "
            "Blasse Felder = Empfehlung fürs nächste Training (Hover für Details)."
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
    app_banner("Bearbeiten & Löschen")
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
            st.toast(f"{n} Eintrag/Einträge vom {date} gelöscht", icon="🗑️")
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
            st.toast(f"{exercise} am {date} aktualisiert", icon="✅")
            st.rerun()
        with action_r:
            confirm_ex = st.checkbox("Löschen bestätigen", key=f"confirm_ex_{date}_{exercise}")
            if st.button("🗑 Übung löschen", key=f"del_ex_{date}_{exercise}", disabled=not confirm_ex):
                db.delete_exercise(user, date, exercise)
                st.toast(f"{exercise} am {date} gelöscht", icon="🗑️")
                st.rerun()

        st.divider()


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------
def main() -> None:
    inject_css()  # globales Styling (auch für die Login-Seite)

    # Login vorschalten – ohne gültigen Account geht es nicht weiter.
    user = auth.require_login()
    if not user:
        st.stop()

    # Begrüßung direkt nach erfolgreichem Login (überlebt den Rerun via Toast).
    if st.session_state.pop("just_logged_in", False):
        st.toast(f"Willkommen zurück, {user}! 💪", icon="👋")

    page = render_sidebar(user)

    if page == "Training eintragen":
        render_input_page(user)
    elif page == "Auswertung":
        render_dashboard()
    else:
        render_manage_page(user)


if __name__ == "__main__":
    main()
