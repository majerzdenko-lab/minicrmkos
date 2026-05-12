import os
import threading
from datetime import datetime, timedelta, date, time as dtime
from functools import wraps

from flask import Flask, render_template, redirect, url_for, request, flash, session
from werkzeug.security import check_password_hash, generate_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import resend
from models import db, Contact, Course, ArchivedCourse, EmailTemplate, CourseSession, WaitingList, STATUS_ORDER, SOURCES

app = Flask(__name__)

db_url = os.environ.get("DATABASE_URL", "")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url or "sqlite:///crm.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

resend.api_key = os.environ.get("RESEND_API_KEY", "")

db.init_app(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


# ── Auth ───────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        admin_user = os.environ.get("ADMIN_USERNAME", "admin")
        admin_hash = os.environ.get("ADMIN_PASSWORD_HASH", "")
        if not admin_hash:
            error = "Heslo administrátora nie je nastavené. Nastavte ADMIN_PASSWORD_HASH."
        elif username == admin_user and check_password_hash(admin_hash, password):
            session["logged_in"] = True
            session.permanent = True
            next_url = request.args.get("next") or url_for("index")
            return redirect(next_url)
        else:
            error = "Nesprávne meno alebo heslo."
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.template_filter("slug")
def slug_filter(s):
    replacements = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ý": "y",
        "ž": "z", "š": "s", "č": "c", "ť": "t", "ň": "n", "ľ": "l",
        "ĺ": "l", "ŕ": "r", "ô": "o", "ä": "a", " ": "-",
    }
    result = s.lower()
    for k, v in replacements.items():
        result = result.replace(k, v)
    return result


@app.template_filter("fmt_date")
def fmt_date_filter(d):
    if d is None:
        return "—"
    return d.strftime("%-d. %-m. %Y")


@app.template_filter("fmt_time")
def fmt_time_filter(t):
    if t is None:
        return "—"
    return t.strftime("%H:%M")


@app.context_processor
def inject_globals():
    course = Course.query.first()
    confirmed = Contact.query.filter_by(status="potvrdený").count()
    return dict(
        course=course,
        confirmed_count=confirmed,
        status_order=STATUS_ORDER,
        sources=SOURCES,
    )


DEFAULT_TEMPLATES = [
    (
        "záujemca",
        "Záujem o kurz kosenia",
        "Dobrý deň {meno},\n\nďakujeme za Váš záujem o kurz kosenia. Radi by sme Vám zaslali ďalšie informácie.\n\nAk máte otázky, neváhajte nás kontaktovať.\n\nS pozdravom",
    ),
    (
        "termín poslaný",
        "Termín kurzu kosenia",
        "Dobrý deň {meno},\n\nposielame Vám termín kurzu kosenia. Prosíme o potvrdenie Vašej účasti odpoveďou na tento email.\n\nS pozdravom",
    ),
    (
        "potvrdený",
        "Potvrdenie účasti na kurze kosenia",
        "Dobrý deň {meno},\n\npotvrdili ste účasť na kurze kosenia. Tešíme sa na Vás!\n\nPodrobné informácie o priebehu kurzu Vám zašleme čoskoro.\n\nS pozdravom",
    ),
    (
        "info ku kurzu odoslané",
        "Informácie ku kurzu kosenia",
        "Dobrý deň {meno},\n\nposielame Vám všetky potrebné informácie ku kurzu kosenia.\n\nAk máte otázky, sme Vám k dispozícii.\n\nS pozdravom",
    ),
    (
        "absolvoval",
        "Ďakujeme za účasť na kurze",
        "Dobrý deň {meno},\n\nďakujeme za Vašu účasť na kurze kosenia. Dúfame, že ste boli spokojní.\n\nBudeme radi, ak nám zanecháte spätnú väzbu.\n\nS pozdravom",
    ),
    (
        "zrušil",
        "Zrušenie účasti na kurze",
        "Dobrý deň {meno},\n\nberie na vedomie Vaše zrušenie účasti. Ak by ste mali záujem v budúcnosti, neváhajte nás kontaktovať.\n\nS pozdravom",
    ),
]


def run_migrations():
    """Add new columns to existing tables without dropping data."""
    for sql in [
        "ALTER TABLE contact ADD COLUMN course_ref VARCHAR(200)",
        "ALTER TABLE contact ADD COLUMN height VARCHAR(20)",
        "ALTER TABLE contact ADD COLUMN session_id INTEGER REFERENCES course_session(id)",
        "ALTER TABLE contact ADD COLUMN reminder_sent BOOLEAN DEFAULT FALSE",
    ]:
        try:
            with db.engine.connect() as conn:
                conn.execute(db.text(sql))
                conn.commit()
        except Exception:
            pass  # column already exists


def seed_defaults():
    if EmailTemplate.query.count() == 0:
        for status, subject, body in DEFAULT_TEMPLATES:
            db.session.add(EmailTemplate(status=status, subject=subject, body=body))
    if Course.query.count() == 0:
        db.session.add(Course(name="Kurz kosenia", capacity=10))
    db.session.commit()


with app.app_context():
    db.create_all()
    run_migrations()
    seed_defaults()



def send_mail(to, subject, body):
    """Send email via Resend API in a background thread."""
    if not os.environ.get("RESEND_API_KEY"):
        return
    mail_from = os.environ.get("MAIL_FROM", "onboarding@resend.dev")
    recipients = [to] if isinstance(to, str) else to
    def _send():
        try:
            resend.api_key = os.environ.get("RESEND_API_KEY", "")
            resend.Emails.send({
                "from": mail_from,
                "to": recipients,
                "subject": subject,
                "text": body,
            })
        except Exception as e:
            app.logger.error(f"send_mail failed: {e}")
    threading.Thread(target=_send, daemon=True).start()


def first_name(full_name):
    return (full_name or "").split()[0] if full_name else ""


def notify_waiting_list(session_id):
    """Notify first person on waiting list that a spot opened. Returns True if notified."""
    first = WaitingList.query.filter_by(session_id=session_id).order_by(WaitingList.created_at).first()
    if not first:
        return False
    if first.email:
        sess = CourseSession.query.get(session_id)
        sess_label = course_label(sess) if sess else "kurz"
        base_url = os.environ.get("APP_URL", "")
        reg_link = f"{base_url}/prihlasenie/{session_id}" if base_url else f"/prihlasenie/{session_id}"
        send_mail(
            first.email,
            f"Uvoľnilo sa miesto — {sess_label}",
            f"Dobrý deň {first.name},\n\nuvoľnilo sa miesto na kurze: {sess_label}.\n\nPrihlásenie: {reg_link}\n\nS pozdravom\nVerselý Kosec"
        )
    db.session.delete(first)
    db.session.commit()
    return True


def course_label(obj):
    """Human-readable label for a Course or CourseSession, used as course_ref text."""
    if not obj or not obj.name:
        return ""
    parts = [obj.name]
    if obj.date:
        parts.append(obj.date.strftime("%-d. %-m. %Y"))
    return " · ".join(parts)


# ── Index ──────────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    status_filter = request.args.get("status", "")
    query = Contact.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    contacts = query.order_by(Contact.created_at.desc()).all()
    now = datetime.utcnow()
    threshold = now - timedelta(days=4)
    stale_ids = {
        c.id for c in contacts
        if c.status_changed_at and c.status_changed_at < threshold
    }
    days_map = {
        c.id: (now - c.status_changed_at).days if c.status_changed_at else 0
        for c in contacts
    }
    counts = {s: Contact.query.filter_by(status=s).count() for s in STATUS_ORDER}
    total = sum(counts.values())
    sessions = CourseSession.query.filter_by(is_active=True).order_by(CourseSession.date).all()
    return render_template(
        "index.html",
        contacts=contacts,
        stale_ids=stale_ids,
        days_map=days_map,
        status_filter=status_filter,
        counts=counts,
        total=total,
        sessions=sessions,
    )


# ── Contact CRUD ───────────────────────────────────────────────────────────────

@app.route("/contact/add", methods=["POST"])
@login_required
def contact_add():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Meno je povinné.", "error")
        return redirect(url_for("index"))
    course = Course.query.first()
    contact = Contact(
        name=name,
        phone=request.form.get("phone", "").strip(),
        email=request.form.get("email", "").strip(),
        source=request.form.get("source", "iné"),
        course_ref=course_label(course) if course and course.name else "",
    )
    db.session.add(contact)
    db.session.commit()
    flash(f"Kontakt {name} pridaný.", "success")
    return redirect(url_for("index"))


@app.route("/contact/<int:id>/advance", methods=["POST"])
@login_required
def contact_advance(id):
    contact = Contact.query.get_or_404(id)
    if contact.status in STATUS_ORDER:
        idx = STATUS_ORDER.index(contact.status)
        if idx < len(STATUS_ORDER) - 1:
            contact.status = STATUS_ORDER[idx + 1]
            contact.status_changed_at = datetime.utcnow()
            db.session.commit()
            if contact.status == "zrušil" and contact.session_id:
                if notify_waiting_list(contact.session_id):
                    flash("Miesto uvoľnené — prvý na čakacej listine bol notifikovaný.", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/contact/<int:id>/regress", methods=["POST"])
@login_required
def contact_regress(id):
    contact = Contact.query.get_or_404(id)
    if contact.status in STATUS_ORDER:
        idx = STATUS_ORDER.index(contact.status)
        if idx > 0:
            contact.status = STATUS_ORDER[idx - 1]
            contact.status_changed_at = datetime.utcnow()
            db.session.commit()
    return redirect(request.referrer or url_for("index"))


@app.route("/contact/<int:id>/send-email", methods=["POST"])
@login_required
def contact_send_email(id):
    contact = Contact.query.get_or_404(id)
    if not contact.email:
        flash("Kontakt nemá zadaný email.", "error")
        return redirect(url_for("contact_detail", id=id))
    template = EmailTemplate.query.filter_by(status=contact.status).first()
    if not template:
        flash("Pre tento stav nie je nastavená šablóna.", "error")
        return redirect(url_for("contact_detail", id=id))
    subject = template.subject.replace("{meno}", first_name(contact.name))
    body = template.body.replace("{meno}", first_name(contact.name))
    send_mail(contact.email, subject, body)
    flash(f"Email odoslaný na {contact.email}.", "success")
    return redirect(url_for("contact_detail", id=id))


@app.route("/contact/<int:id>/assign-course", methods=["POST"])
@login_required
def contact_assign_course(id):
    contact = Contact.query.get_or_404(id)
    session_id = request.form.get("session_id", "").strip()
    if session_id and session_id.isdigit():
        sess = CourseSession.query.get(int(session_id))
        if sess:
            contact.session_id = sess.id
            contact.course_ref = course_label(sess)
            db.session.commit()
            flash(f"Priradené ku termínu: {contact.course_ref}", "success")
            return redirect(request.referrer or url_for("index"))
    course = Course.query.first()
    label = course_label(course)
    if not label:
        flash("Nie je nastavený žiadny aktívny kurz.", "error")
    else:
        contact.course_ref = label
        db.session.commit()
        flash(f"Priradené ku kurzu: {label}", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/contact/<int:id>", methods=["GET", "POST"])
@login_required
def contact_detail(id):
    contact = Contact.query.get_or_404(id)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Meno je povinné.", "error")
            return redirect(url_for("contact_detail", id=id))
        contact.name = name
        contact.phone = request.form.get("phone", "").strip()
        contact.email = request.form.get("email", "").strip()
        contact.source = request.form.get("source", contact.source)
        new_status = request.form.get("status", contact.status)
        status_changed = new_status != contact.status
        if status_changed:
            contact.status = new_status
            contact.status_changed_at = datetime.utcnow()
        contact.note = request.form.get("note", "")
        new_session_id_str = request.form.get("session_id", "").strip()
        old_session_id = contact.session_id
        if new_session_id_str == "remove":
            contact.session_id = None
            contact.course_ref = ""
        elif new_session_id_str.isdigit() and int(new_session_id_str) > 0:
            sess = CourseSession.query.get(int(new_session_id_str))
            if sess:
                contact.session_id = sess.id
                contact.course_ref = course_label(sess)
        else:
            contact.course_ref = request.form.get("course_ref", "").strip()
            if not new_session_id_str:
                contact.session_id = None
        db.session.commit()
        if status_changed and new_status == "zrušil" and (contact.session_id or old_session_id):
            notify_sid = contact.session_id or old_session_id
            if notify_waiting_list(notify_sid):
                flash("Miesto uvoľnené — prvý na čakacej listine bol notifikovaný.", "success")
        flash("Kontakt uložený.", "success")
        return redirect(url_for("contact_detail", id=id))

    email_template = EmailTemplate.query.filter_by(status=contact.status).first()
    all_templates = {
        t.status: {"subject": t.subject or "", "body": t.body or ""}
        for t in EmailTemplate.query.all()
    }
    sessions = CourseSession.query.order_by(CourseSession.date).all()
    return render_template(
        "contact.html",
        contact=contact,
        email_template=email_template,
        all_templates=all_templates,
        sessions=sessions,
    )


@app.route("/contact/<int:id>/delete", methods=["POST"])
@login_required
def contact_delete(id):
    contact = Contact.query.get_or_404(id)
    name = contact.name
    session_id = contact.session_id
    db.session.delete(contact)
    db.session.commit()
    flash(f"Kontakt {name} zmazaný.", "success")
    if session_id:
        if notify_waiting_list(session_id):
            flash("Miesto uvoľnené — prvý na čakacej listine bol notifikovaný.", "success")
    return redirect(url_for("index"))


# ── Settings ───────────────────────────────────────────────────────────────────

@app.route("/settings")
@login_required
def settings():
    course = Course.query.first()
    templates = {t.status: t for t in EmailTemplate.query.all()}
    sessions = CourseSession.query.order_by(CourseSession.date).all()
    base_url = request.host_url.rstrip("/").replace("http://", "https://", 1)
    return render_template("settings.html", course=course, templates=templates,
                           sessions=sessions, base_url=base_url)


@app.route("/settings/course", methods=["POST"])
@login_required
def settings_course():
    course = Course.query.first()
    if not course:
        course = Course()
        db.session.add(course)
    course.name = request.form.get("name", "").strip()
    course.location = request.form.get("location", "").strip()
    try:
        course.capacity = int(request.form.get("capacity", 10))
    except ValueError:
        course.capacity = 10
    date_str = request.form.get("date", "").strip()
    time_str = request.form.get("time", "").strip()
    try:
        course.date = date.fromisoformat(date_str) if date_str else None
    except ValueError:
        course.date = None
    try:
        if time_str:
            h, m = time_str.split(":")
            course.time = dtime(int(h), int(m))
        else:
            course.time = None
    except (ValueError, TypeError):
        course.time = None
    db.session.commit()
    flash("Kurz uložený.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/template/<path:status>", methods=["POST"])
@login_required
def settings_template(status):
    template = EmailTemplate.query.filter_by(status=status).first()
    if not template:
        template = EmailTemplate(status=status)
        db.session.add(template)
    template.subject = request.form.get("subject", "").strip()
    template.body = request.form.get("body", "").strip()
    db.session.commit()
    flash(f"Šablóna pre '{status}' uložená.", "success")
    next_url = request.form.get("_next", "")
    return redirect(next_url if next_url else url_for("settings"))


# ── History ────────────────────────────────────────────────────────────────────

@app.route("/history")
@login_required
def history():
    archived = ArchivedCourse.query.order_by(ArchivedCourse.archived_at.desc()).all()
    return render_template("history.html", archived=archived)


@app.route("/history/archive", methods=["POST"])
@login_required
def history_archive():
    course = Course.query.first()
    if not course or not course.name:
        flash("Žiadny aktívny kurz na archiváciu.", "error")
        return redirect(url_for("history"))
    participants = Contact.query.filter_by(status="potvrdený").count()
    db.session.add(ArchivedCourse(
        name=course.name,
        date=course.date,
        time=course.time,
        location=course.location,
        capacity=course.capacity,
        participants_count=participants,
    ))
    course.name = ""
    course.date = None
    course.time = None
    course.location = ""
    course.capacity = 10
    db.session.commit()
    flash("Kurz bol archivovaný.", "success")
    return redirect(url_for("history"))


# ── Course sessions (admin) ────────────────────────────────────────────────────

@app.route("/settings/sessions/add", methods=["POST"])
@login_required
def session_add():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Názov termínu je povinný.", "error")
        return redirect(url_for("settings"))
    date_str = request.form.get("date", "").strip()
    time_str = request.form.get("time", "").strip()
    location = request.form.get("location", "").strip()
    try:
        capacity = int(request.form.get("capacity", 10))
    except ValueError:
        capacity = 10
    sess = CourseSession(name=name, location=location, capacity=capacity)
    try:
        sess.date = date.fromisoformat(date_str) if date_str else None
    except ValueError:
        sess.date = None
    try:
        if time_str:
            h, m = time_str.split(":")
            sess.time = dtime(int(h), int(m))
    except (ValueError, TypeError):
        sess.time = None
    db.session.add(sess)
    db.session.commit()
    flash(f"Termín '{name}' pridaný.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/sessions/<int:id>/toggle", methods=["POST"])
@login_required
def session_toggle(id):
    sess = CourseSession.query.get_or_404(id)
    sess.is_active = not sess.is_active
    db.session.commit()
    return redirect(url_for("settings"))


@app.route("/settings/sessions/<int:id>/delete", methods=["POST"])
@login_required
def session_delete(id):
    sess = CourseSession.query.get_or_404(id)
    db.session.delete(sess)
    db.session.commit()
    flash("Termín zmazaný.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/sessions/<int:id>/edit", methods=["POST"])
@login_required
def session_edit(id):
    sess = CourseSession.query.get_or_404(id)
    sess.name = request.form.get("name", "").strip() or sess.name
    sess.location = request.form.get("location", "").strip()
    date_str = request.form.get("date", "").strip()
    time_str = request.form.get("time", "").strip()
    try:
        sess.date = date.fromisoformat(date_str) if date_str else None
    except ValueError:
        pass
    try:
        if time_str:
            h, m = time_str.split(":")
            sess.time = dtime(int(h), int(m))
        else:
            sess.time = None
    except (ValueError, TypeError):
        pass
    try:
        sess.capacity = int(request.form.get("capacity", sess.capacity))
    except ValueError:
        pass
    db.session.commit()
    flash(f"Termín '{sess.name}' aktualizovaný.", "success")
    return redirect(url_for("settings"))


@app.route("/session/<int:id>")
@login_required
def session_detail(id):
    sess = CourseSession.query.get_or_404(id)
    contacts = Contact.query.filter_by(session_id=id).order_by(Contact.name).all()
    waiting = WaitingList.query.filter_by(session_id=id).order_by(WaitingList.created_at).all()
    return render_template("session_detail.html", sess=sess, contacts=contacts, waiting=waiting)


# ── Public registration ────────────────────────────────────────────────────────

@app.route("/kurzy")
def kurzy_widget():
    sessions = (CourseSession.query
                .filter_by(is_active=True)
                .order_by(CourseSession.date)
                .all())
    return render_template("kurzy.html", sessions=sessions, notify_sent=False)


@app.route("/kurzy/notifikacia", methods=["POST"])
@limiter.limit("5 per minute; 20 per hour")
def kurzy_notify():
    if request.form.get("website"):  # honeypot
        sessions = CourseSession.query.filter_by(is_active=True).order_by(CourseSession.date).all()
        return render_template("kurzy.html", sessions=sessions, notify_sent=True)
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    if name and (email or phone):
        contact = Contact(
            name=name,
            email=email,
            phone=phone,
            source="web",
            note="Záujem o oznámenie termínov kurzu",
        )
        db.session.add(contact)
        db.session.commit()
        admin = os.environ.get("ADMIN_EMAIL", "")
        if admin:
            send_mail(admin,
                f"Nový záujemca o kurz: {name}",
                f"Meno: {name}\nEmail: {email or '—'}\nTelefón: {phone or '—'}\n\nZáujem o oznámenie termínov kurzu.")
    sessions = (CourseSession.query
                .filter_by(is_active=True)
                .order_by(CourseSession.date)
                .all())
    return render_template("kurzy.html", sessions=sessions, notify_sent=True)


@app.route("/prihlasenie/<int:session_id>", methods=["GET", "POST"])
@limiter.limit("10 per minute; 30 per hour")
def prihlasenie(session_id):
    sess = CourseSession.query.get_or_404(session_id)
    if not sess.is_active:
        return render_template("prihlasenie.html", sess=None, is_open=False)

    error = None
    if request.method == "POST":
        if request.form.get("website"):  # honeypot
            return redirect(url_for("prihlasenie_dakujeme", session_id=sess.id))
        first = request.form.get("first_name", "").strip()
        last  = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        height = request.form.get("height", "").strip()
        if not first or not last:
            error = "Vyplňte prosím meno aj priezvisko."
        elif not phone and not email:
            error = "Zadajte aspoň telefón alebo email."
        else:
            name = f"{first} {last}"
            contact = Contact(
                name=name,
                phone=phone,
                email=email,
                height=height,
                source="web",
                course_ref=course_label(sess),
                session_id=sess.id,
            )
            db.session.add(contact)
            db.session.commit()
            admin = os.environ.get("ADMIN_EMAIL", "")
            if admin:
                sess_label = course_label(sess)
                send_mail(admin,
                    f"Nová prihláška: {name} — {sess_label}",
                    f"Meno: {name}\nEmail: {email or '—'}\nTelefón: {phone or '—'}\nVýška: {height or '—'}\nKurz: {sess_label}")
            if email:
                tmpl = EmailTemplate.query.filter_by(status="potvrdený").first()
                if tmpl:
                    send_mail(email,
                        tmpl.subject.replace("{meno}", first),
                        tmpl.body.replace("{meno}", first))
            return redirect(url_for("prihlasenie_dakujeme", session_id=sess.id))

    return render_template("prihlasenie.html", sess=sess, is_open=True, error=error)


@app.route("/prihlasenie/<int:session_id>/dakujeme")
def prihlasenie_dakujeme(session_id):
    sess = CourseSession.query.get(session_id)
    return render_template("dakujeme.html", sess=sess)


@app.route("/prihlasenie/<int:session_id>/waiting", methods=["POST"])
@limiter.limit("5 per minute; 15 per hour")
def prihlasenie_waiting(session_id):
    sess = CourseSession.query.get_or_404(session_id)
    if request.form.get("website"):  # honeypot
        return redirect(url_for("prihlasenie_dakujeme", session_id=sess.id))
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    if not name or (not email and not phone):
        return redirect(url_for("prihlasenie", session_id=session_id))
    entry = WaitingList(session_id=sess.id, name=name, email=email, phone=phone)
    db.session.add(entry)
    db.session.commit()
    admin = os.environ.get("ADMIN_EMAIL", "")
    if admin:
        send_mail(admin,
            f"Čakacia listina: {name} — {course_label(sess)}",
            f"Meno: {name}\nEmail: {email or '—'}\nTelefón: {phone or '—'}\nTermín: {course_label(sess)}")
    return redirect(url_for("prihlasenie_dakujeme", session_id=sess.id))


# Legacy route — keep working if someone has the old link
@app.route("/prihlasenie", methods=["GET"])
def prihlasenie_legacy():
    sessions = (CourseSession.query
                .filter_by(is_active=True)
                .order_by(CourseSession.date)
                .all())
    if sessions:
        return redirect(url_for("prihlasenie", session_id=sessions[0].id))
    return render_template("prihlasenie.html", sess=None, is_open=False)


# ── Cron ───────────────────────────────────────────────────────────────────────

@app.route("/cron/send-reminders")
def cron_send_reminders():
    token = os.environ.get("CRON_SECRET", "")
    if not token or request.args.get("token") != token:
        from flask import abort
        abort(403)
    cutoff_from = date.today() + timedelta(days=3)
    cutoff_to   = date.today() + timedelta(days=4)
    sessions = CourseSession.query.filter(
        CourseSession.date >= cutoff_from,
        CourseSession.date < cutoff_to,
        CourseSession.is_active == True,
    ).all()
    template = EmailTemplate.query.filter_by(status="info ku kurzu odoslané").first()
    sent = 0
    for sess in sessions:
        contacts = Contact.query.filter_by(
            session_id=sess.id, reminder_sent=False
        ).filter(Contact.status.in_(["potvrdený", "info ku kurzu odoslané"])).all()
        for c in contacts:
            if c.email and template:
                send_mail(
                    c.email,
                    template.subject.replace("{meno}", first_name(c.name)),
                    template.body.replace("{meno}", first_name(c.name)),
                )
                c.reminder_sent = True
                sent += 1
    db.session.commit()
    return f"OK: {sent} reminders sent", 200


# ── Bulk email ─────────────────────────────────────────────────────────────────

@app.route("/bulk-email", methods=["GET"])
@login_required
def bulk_email_form():
    ids = [int(i) for i in request.args.get("ids", "").split(",") if i.strip().isdigit()]
    if not ids:
        flash("Nevybratí žiadni kontakti.", "error")
        return redirect(url_for("index"))
    contacts = Contact.query.filter(Contact.id.in_(ids)).all()
    templates = EmailTemplate.query.all()
    return render_template("bulk_email.html", contacts=contacts, templates=templates)


@app.route("/bulk-email", methods=["POST"])
@login_required
def bulk_email_send():
    ids = [int(i) for i in request.form.get("ids", "").split(",") if i.strip().isdigit()]
    subject_tpl = request.form.get("subject", "").strip()
    body_tpl = request.form.get("body", "").strip()
    if not subject_tpl or not body_tpl:
        flash("Vyplňte predmet aj text emailu.", "error")
        return redirect(url_for("bulk_email_form", ids=",".join(str(i) for i in ids)))
    contacts = Contact.query.filter(Contact.id.in_(ids)).all()
    sent, skipped = 0, 0
    for c in contacts:
        if not c.email:
            skipped += 1
            continue
        send_mail(
            c.email,
            subject_tpl.replace("{meno}", first_name(c.name)),
            body_tpl.replace("{meno}", first_name(c.name)),
        )
        sent += 1
    parts = [f"Email odoslaný {sent} kontaktom."]
    if skipped:
        parts.append(f"{skipped} preskočených (bez emailu).")
    flash(" ".join(parts), "success")
    return redirect(url_for("index"))


@app.route("/bulk/status", methods=["POST"])
@login_required
def bulk_status_change():
    ids = [int(i) for i in request.form.get("ids", "").split(",") if i.strip().isdigit()]
    new_status = request.form.get("status", "").strip()
    if not new_status or new_status not in STATUS_ORDER:
        flash("Neplatný stav.", "error")
        return redirect(url_for("index"))
    updated = 0
    for contact in Contact.query.filter(Contact.id.in_(ids)).all():
        if contact.status != new_status:
            contact.status = new_status
            contact.status_changed_at = datetime.utcnow()
            if new_status == "zrušil" and contact.session_id:
                notify_waiting_list(contact.session_id)
            updated += 1
    db.session.commit()
    flash(f'Stav zmenený na "{new_status}" pre {updated} kontaktov.', "success")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
