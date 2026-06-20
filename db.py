"""
db.py
-----
Kapselt die komplette MongoDB-Anbindung (MongoDB Atlas via pymongo).

Der Connection-String wird NICHT im Code gespeichert, sondern aus
Streamlit-Secrets (st.secrets) oder ersatzweise aus einer Umgebungsvariable
(MONGO_URI) gelesen. So bleibt das Passwort aus dem Repository heraus.
"""

import os
from urllib.parse import quote_plus

import streamlit as st
from pymongo import MongoClient
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

# Feste Namen für Datenbank und Collection.
DB_NAME = "training_diary"
COLLECTION_NAME = "trainings"


def _secret(key: str) -> str | None:
    """
    Liest einen Wert bevorzugt aus st.secrets, ersatzweise aus einer
    gleichnamigen Umgebungsvariable (Großschreibung). Gibt None zurück,
    wenn nichts gesetzt ist.
    """
    # st.secrets kann eine Exception werfen, wenn gar keine secrets.toml
    # existiert -> defensiv abfangen.
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key.upper())


def _get_mongo_uri() -> str:
    """
    Baut den Mongo-Connection-String.

    Zwei Wege werden unterstützt:

    1. Komponenten (EMPFOHLEN, sonderzeichensicher):
       mongo_username, mongo_password, mongo_host  (+ optional mongo_appname)
       Username/Passwort werden hier URL-encodiert, damit Sonderzeichen
       (@ : / ? # usw.) den String nicht zerstören.

    2. Fertiger String:
       mongo_uri  -> wird unverändert verwendet.

    Wirft einen klaren Fehler, wenn nichts Brauchbares gesetzt ist.
    """
    # Weg 1: Komponenten -> selbst zusammenbauen mit korrektem Encoding.
    user = _secret("mongo_username")
    password = _secret("mongo_password")
    host = _secret("mongo_host")
    if user and password and host:
        app_name = _secret("mongo_appname") or "train"
        return (
            f"mongodb+srv://{quote_plus(user)}:{quote_plus(password)}@{host}/"
            f"?appName={quote_plus(app_name)}"
        )

    # Weg 2: fertiger String als Fallback.
    uri = _secret("mongo_uri")
    if uri:
        return uri

    raise RuntimeError(
        "Keine MongoDB-Zugangsdaten gefunden. Lege in .streamlit/secrets.toml "
        "entweder mongo_username/mongo_password/mongo_host an (empfohlen) "
        "oder einen fertigen mongo_uri."
    )


@st.cache_resource(show_spinner="Verbinde mit MongoDB ...")
def get_client() -> MongoClient:
    """
    Erstellt einen MongoClient und cached ihn über den gesamten App-Lebenszyklus.

    @st.cache_resource sorgt dafür, dass NICHT bei jedem Streamlit-Rerun eine
    neue Verbindung aufgebaut wird (das wäre langsam und würde den Connection-Pool
    von Atlas unnötig belasten).
    """
    uri = _get_mongo_uri()
    # serverSelectionTimeoutMS: schneller Fehler statt 30s Hängen, falls die
    # Verbindung (z. B. IP nicht freigegeben) nicht klappt.
    client = MongoClient(uri, serverSelectionTimeoutMS=5000, appname="train")
    return client


def get_collection():
    """Liefert die Collection-Referenz für die Trainingseinträge."""
    return get_client()[DB_NAME][COLLECTION_NAME]


def ping() -> tuple[bool, str]:
    """
    Testet die Verbindung aktiv (für eine Statusanzeige in der Sidebar).

    Returns:
        (ok, message)
    """
    try:
        get_client().admin.command("ping")
        return True, "Verbindung zu MongoDB Atlas steht."
    except ServerSelectionTimeoutError:
        return False, (
            "Keine Verbindung zu Atlas. Prüfe: ist deine IP unter "
            "'Network Access' freigegeben (0.0.0.0/0 zum Testen)?"
        )
    except PyMongoError as exc:
        return False, f"MongoDB-Fehler: {exc}"


def insert_training(documents: list[dict]) -> int:
    """
    Speichert die Dokumente einer Trainingseinheit (i. d. R. 3 Dokumente,
    eines pro Übung) in einem Rutsch.

    Returns:
        Anzahl der tatsächlich eingefügten Dokumente.
    """
    if not documents:
        return 0
    result = get_collection().insert_many(documents)
    return len(result.inserted_ids)


def fetch_trainings(user: str | None = None) -> list[dict]:
    """
    Holt alle Trainingsdokumente, optional gefiltert nach Nutzer.

    Sortiert nach Datum (aufsteigend), damit Zeitreihen direkt passen.
    Das interne _id-Feld wird nicht mitgeliefert (für DataFrames irrelevant).
    """
    query = {"user": user} if user else {}
    cursor = get_collection().find(query, {"_id": 0}).sort("date", 1)
    return list(cursor)


def update_exercise(user: str, date: str, exercise: str, sets: list[dict]) -> int:
    """
    Aktualisiert die Sätze einer Übung an einem bestimmten Tag.

    Identität eines Eintrags = (user, date, exercise). Gibt die Anzahl der
    geänderten Dokumente zurück.
    """
    result = get_collection().update_one(
        {"user": user, "date": date, "exercise": exercise},
        {"$set": {"sets": sets}},
    )
    return result.modified_count


def delete_exercise(user: str, date: str, exercise: str) -> int:
    """Löscht eine einzelne Übung an einem Tag. Returns: Anzahl gelöscht."""
    result = get_collection().delete_many(
        {"user": user, "date": date, "exercise": exercise}
    )
    return result.deleted_count


def delete_training_day(user: str, date: str) -> int:
    """Löscht ALLE Übungen eines Nutzers an einem Tag. Returns: Anzahl gelöscht."""
    result = get_collection().delete_many({"user": user, "date": date})
    return result.deleted_count
