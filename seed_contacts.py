"""
Jednorazový import kontaktov.
Spustenie lokálne s Railway DB:
  railway run python seed_contacts.py
Alebo lokálne (SQLite):
  python seed_contacts.py
"""
import os, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import app, db
from models import Contact

NEW_CONTACTS = [
    {"name": "Lucka",              "email": "lucia.sarudyova@gmail.com",   "phone": "+421948461580"},
    {"name": "Marián Šabo",        "email": "sabo385@gmail.com"},
    {"name": "Lukáš Lalinský",     "email": "l.lalinsky@gmail.com"},
    {"name": "Tomáš Maňák",        "email": "tomasmanak07@gmail.com"},
    {"name": "Marta Klottonová",   "email": "klottonova.kunesov@gmail.com"},
    {"name": "Juraj Sagat",        "email": "sagatjuraj@gmail.com"},
    {"name": "Katarína Sabolíková","email": "sabolikova.katka@gmail.com"},
    {"name": "Ján Horňák",         "email": "hornakj@gmail.com"},
    {"name": "Alena Boháčová",     "email": "alenavrablikova@azet.sk"},
]

with app.app_context():
    added = 0
    skipped = 0
    for c in NEW_CONTACTS:
        if c.get("email") and Contact.query.filter_by(email=c["email"]).first():
            print(f"  SKIP (už existuje): {c['name']} <{c['email']}>")
            skipped += 1
            continue
        contact = Contact(
            name=c["name"],
            email=c.get("email"),
            phone=c.get("phone"),
            source="iné",
            status="záujemca",
            created_at=datetime.utcnow(),
            status_changed_at=datetime.utcnow(),
        )
        db.session.add(contact)
        print(f"  + {c['name']}")
        added += 1
    db.session.commit()
    print(f"\nHotovo: {added} pridaných, {skipped} preskočených.")
