from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

STATUS_ORDER = [
    "záujemca",
    "termín poslaný",
    "potvrdený",
    "info ku kurzu odoslané",
    "absolvoval",
    "zrušil",
]

SOURCES = ["mail", "telefón", "najzazitky.sk", "web", "iné"]


class Contact(db.Model):
    __tablename__ = "contact"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(50))
    email = db.Column(db.String(120))
    source = db.Column(db.String(50), default="iné")
    status = db.Column(db.String(50), default="záujemca")
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status_changed_at = db.Column(db.DateTime, default=datetime.utcnow)
    course_ref = db.Column(db.String(200))
    height = db.Column(db.String(20))
    reminder_sent = db.Column(db.Boolean, default=False)
    session_id = db.Column(db.Integer, db.ForeignKey("course_session.id"), nullable=True)
    session = db.relationship("CourseSession", backref="contacts", foreign_keys=[session_id])


class Course(db.Model):
    __tablename__ = "course"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200))
    date = db.Column(db.Date)
    time = db.Column(db.Time)
    location = db.Column(db.String(200))
    capacity = db.Column(db.Integer, default=10)


class ArchivedCourse(db.Model):
    __tablename__ = "archived_course"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200))
    date = db.Column(db.Date)
    time = db.Column(db.Time)
    location = db.Column(db.String(200))
    capacity = db.Column(db.Integer)
    participants_count = db.Column(db.Integer, default=0)
    archived_at = db.Column(db.DateTime, default=datetime.utcnow)


class CourseSession(db.Model):
    __tablename__ = "course_session"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    date = db.Column(db.Date)
    time = db.Column(db.Time)
    location = db.Column(db.String(200))
    capacity = db.Column(db.Integer, default=10)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def registered_count(self):
        return len([c for c in self.contacts])

    @property
    def spots_left(self):
        if self.capacity is None:
            return None
        return max(0, self.capacity - self.registered_count)


class WaitingList(db.Model):
    __tablename__ = "waiting_list"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("course_session.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200))
    phone = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    session = db.relationship("CourseSession", backref="waiting_list")


class EmailTemplate(db.Model):
    __tablename__ = "email_template"
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(50), unique=True, nullable=False)
    subject = db.Column(db.String(200))
    body = db.Column(db.Text)
