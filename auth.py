"""
auth.py
-------
Schlanker Login für die zwei Nutzer.

Die Passwörter liegen NICHT im Code, sondern in den Streamlit-Secrets unter
einem [passwords]-Abschnitt, z. B.:

    [passwords]
    Patric  = "..."
    Sandeep = "..."

Der Vergleich läuft zeitkonstant (hmac.compare_digest), damit man aus der
Antwortzeit nicht auf das Passwort schließen kann.
"""

import hmac

import streamlit as st

import logic


def _password_correct(user: str, password: str) -> bool:
    """Prüft das eingegebene Passwort zeitkonstant gegen die Secrets."""
    try:
        stored = st.secrets["passwords"][user]
    except Exception:
        # Kein [passwords]-Abschnitt / User nicht hinterlegt.
        return False
    return hmac.compare_digest(str(password), str(stored))


def require_login() -> str | None:
    """
    Stellt sicher, dass ein Nutzer eingeloggt ist.

    Returns:
        Den Nutzernamen, wenn eingeloggt – sonst None (dann wurde die
        Login-Maske gezeichnet und der Aufrufer soll st.stop() ausführen).
    """
    # Schon eingeloggt? Direkt zurückgeben.
    if st.session_state.get("auth_user"):
        return st.session_state["auth_user"]

    # Login-Maske.
    st.title("🏋️ Trainingstagebuch – Login")
    st.caption("Bitte mit deinem Account anmelden.")

    with st.form("login_form"):
        user = st.selectbox("Nutzer", logic.USERS)
        password = st.text_input("Passwort", type="password")
        submitted = st.form_submit_button("Anmelden", type="primary")

    if submitted:
        if _password_correct(user, password):
            st.session_state["auth_user"] = user
            # Neu laden, damit die Login-Maske verschwindet und die App startet.
            st.rerun()
        else:
            st.error("Falscher Nutzer oder falsches Passwort.")

    return None


def logout_button() -> None:
    """Zeichnet einen Logout-Button (für die Sidebar)."""
    if st.button("Abmelden"):
        st.session_state.pop("auth_user", None)
        st.rerun()
