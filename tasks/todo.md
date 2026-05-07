# Mini CRM — Todo

## Status: In Progress

### Fáza 1: Skeleton ✓
- [x] requirements.txt, Procfile
- [x] models.py
- [x] app.py (config, db.create_all(), seed)
- [x] .gitignore, .env.example

### Fáza 2: Base template + CSS ✓
- [x] templates/base.html
- [x] static/style.css

### Fáza 3: Index stránka ✓
- [x] GET / (filter, stale_ids)
- [x] index.html
- [x] POST /contact/add
- [x] POST /contact/<id>/advance

### Fáza 4: Detail kontaktu ✓
- [x] GET + POST /contact/<id>
- [x] contact.html

### Fáza 5: Nastavenia ✓
- [x] settings routes
- [x] settings.html

### Fáza 6: História ✓
- [x] history routes
- [x] history.html

### Fáza 7: Dokončenie
- [ ] Manuálne testovanie všetkých tokov
- [ ] Overenie Railway deploy

## Working Notes

- STATUS_ORDER: záujemca → termín poslaný → potvrdený → info ku kurzu odoslané → absolvoval → zrušil
- SOURCES: mail, telefón, najzazitky.sk, iné
- Railway postgres:// fix je v app.py
- SQLite fallback keď DATABASE_URL nie je nastavená
- stale_ids: kontakty >4 dni v rovnakom stave (status_changed_at < now-4days)
