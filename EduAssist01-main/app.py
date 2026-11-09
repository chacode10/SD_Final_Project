"""
Classroom Command Hub - a solo, fully customizable teacher app.
This version is configured for a local SQLite database so it does not depend on MySQL.
On Vercel, the app uses the writable /tmp directory for its SQLite file and uploads.
"""
import io, os, re, json, uuid, datetime as dt
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
from flask import (Flask, request, redirect, url_for, flash, render_template,
                    send_from_directory, abort)
from jinja2 import DictLoader
from sqlalchemy import (create_engine, MetaData, Table, Column, Integer, String, Text, text)
from werkzeug.utils import secure_filename


def default_storage_root():
    # Vercel serverless functions have a writable /tmp directory. For local runs,
    # keep the data in the project folder unless the user overrides it.
    if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return "/tmp"
    return os.getcwd()


# Force a local SQLite database instead of MySQL. This prevents the app from
# failing on Vercel when MySQL credentials are absent.
BASE_STORAGE_DIR = Path(os.getenv("LOCAL_STORAGE_DIR") or default_storage_root())
DB_PATH = Path(os.getenv("DB_PATH") or str(BASE_STORAGE_DIR / "classroom.db"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR") or str(BASE_STORAGE_DIR / "uploads"))
DB_URL = os.getenv("DATABASE_URL") or f"sqlite:///{DB_PATH.as_posix()}"

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me-please")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
engine = create_engine(DB_URL, pool_pre_ping=True, pool_recycle=280)

# ---------------------------------------------------------------- database
md = MetaData()
Table("settings", md, Column("k", String(64), primary_key=True), Column("v", Text))
Table("folders", md, Column("id", Integer, primary_key=True, autoincrement=True),
      Column("name", String(120)), Column("parent_id", Integer, nullable=True))
Table("files", md, Column("id", Integer, primary_key=True, autoincrement=True),
      Column("folder_id", Integer, nullable=True), Column("name", String(255)),
      Column("stored", String(700)), Column("size", Integer), Column("kind", String(12)),
      Column("created", String(19)))
Table("events", md, Column("id", Integer, primary_key=True, autoincrement=True),
      Column("title", String(160)), Column("day", String(10)), Column("time", String(5)),
      Column("kind", String(12)))
Table("sections", md, Column("id", Integer, primary_key=True, autoincrement=True),
      Column("name", String(120)), Column("subject", String(120)), Column("scheme", Text),
      Column("archived", Integer, default=0), Column("completed_on", String(10)))
Table("students", md, Column("id", Integer, primary_key=True, autoincrement=True),
      Column("section_id", Integer), Column("name", String(120)))
Table("scores", md, Column("id", Integer, primary_key=True, autoincrement=True),
      Column("student_id", Integer), Column("comp", String(80)), Column("val", String(12)))
Table("activity", md, Column("id", Integer, primary_key=True, autoincrement=True),
      Column("kind", String(8)), Column("body", String(400)), Column("ts", String(19)),
      Column("is_read", Integer, default=0))


# rest of the file remains unchanged below this point.
