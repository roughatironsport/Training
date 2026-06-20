"""
test_connection.py
------------------
Kleines, eigenständiges Skript zum Prüfen der MongoDB-Verbindung.

Es nutzt bewusst dieselbe Logik wie die App (db.py), liest die Zugangsdaten
also aus .streamlit/secrets.toml (oder Umgebungsvariablen).

Aufruf:
    python test_connection.py
"""

import sys

import db

# Windows-Konsolen nutzen oft cp1252 und können Emojis nicht ausgeben.
# Stdout auf UTF-8 umstellen, damit die ✅/❌-Ausgaben nicht crashen.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main() -> None:
    # 1) Reiner Verbindungstest (ping)
    ok, msg = db.ping()
    if not ok:
        print("❌ Fehler:", msg)
        return
    print("✅ Verbindung steht!", msg)

    # 2) Schreib-/Lese-Test mit einem Wegwerf-Dokument.
    #    Wir schreiben ein klar markiertes Test-Dokument und löschen es danach.
    collection = db.get_collection()
    marker = {"_conn_test": True}
    test_doc = {**marker, "note": "temporärer Verbindungstest"}

    insert_result = collection.insert_one(test_doc)
    print(f"✅ Schreiben OK (eingefügte _id: {insert_result.inserted_id})")

    found = collection.find_one(marker)
    print("✅ Lesen OK " if found else "❌ Lesen fehlgeschlagen")

    deleted = collection.delete_many(marker)
    print(f"🧹 Aufgeräumt: {deleted.deleted_count} Test-Dokument(e) gelöscht")

    print(f"\nDatenbank '{db.DB_NAME}', Collection '{db.COLLECTION_NAME}' ist bereit.")


if __name__ == "__main__":
    main()
