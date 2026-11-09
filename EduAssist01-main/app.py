"""
Classroom Command Hub - a solo, fully customizable teacher app.
Setup and run instructions: see README.md. Settings (MySQL + Cloudinary) go in the .env file.
"""
import io, os, re, json, uuid, datetime as dt
from dotenv import load_dotenv
load_dotenv()
from flask import (Flask, request, redirect, url_for, flash, render_template,
                   send_from_directory, abort)
from jinja2 import DictLoader
from sqlalchemy.engine import URL
from sqlalchemy import (create_engine, MetaData, Table, Column, Integer, String, Text, text)
from werkzeug.utils import secure_filename

if os.getenv("DB_NAME"):   # MySQL (or MariaDB / XAMPP)
    DB_URL = URL.create("mysql+pymysql", username=os.getenv("DB_USER", "root"),
                        password=os.getenv("DB_PASSWORD", ""), host=os.getenv("DB_HOST", "localhost"),
                        port=int(os.getenv("DB_PORT", 3306)), database=os.getenv("DB_NAME"),
                        query={"charset": "utf8mb4"})
else:                      # fallback so the app still runs with no MySQL yet
    DB_URL = os.getenv("DATABASE_URL", "sqlite:///classroom.db")
UPLOAD_DIR = os.path.abspath(os.getenv("UPLOAD_DIR", "uploads"))

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


def q(sql, **p):
    with engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(sql), p)]

def one(sql, **p):
    r = q(sql, **p)
    return r[0] if r else None

def ex(sql, **p):
    with engine.begin() as c:
        return c.execute(text(sql), p).lastrowid

def now():
    return dt.datetime.now().isoformat(timespec="seconds")

def log(body, kind="notif"):
    ex("INSERT INTO activity(kind,body,ts,is_read) VALUES(:k,:b,:t,0)", k=kind, b=body, t=now())

# ---------------------------------------------------------------- settings
DEFAULTS = dict(
    teacher="Ma. Fe. B. Villamar", school="Banga Elementary School", app_name="EduAssist",
    accent="#0e5a78", sidebar="#10294a", bg="#e1eff7", avatar="",
    lbl_dashboard="Dashboard", lbl_plans="Lesson Plans", lbl_grades="Grades",
    lbl_notifs="Notifications", lbl_settings="Settings",
    w_schedule="1", w_activity="1", w_resources="1", w_status="1",
    links="Department site|https://example.com",
    scheme="Quizzes: 20\nActivities: 20\nProjects: 25\nExam: 35 | Long Test, Periodical Test")

def cfg():
    d = dict(DEFAULTS)
    d.update({r["k"]: r["v"] for r in q("SELECT k,v FROM settings")})
    d["app_name"] = DEFAULTS["app_name"]   # fixed: not editable
    return d

def put(k, v):
    ex("DELETE FROM settings WHERE k=:k", k=k)
    ex("INSERT INTO settings(k,v) VALUES(:k,:v)", k=k, v=v)

# ---------------------------------------------------------------- storage (Cloudinary or local)
CLOUD = bool(os.getenv("CLOUDINARY_URL") or os.getenv("CLOUDINARY_CLOUD_NAME"))
if CLOUD:
    import cloudinary, cloudinary.uploader
    if os.getenv("CLOUDINARY_CLOUD_NAME"):
        cloudinary.config(cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"), api_key=os.getenv("CLOUDINARY_API_KEY"),
                          api_secret=os.getenv("CLOUDINARY_API_SECRET"), secure=True)

def store_save(f):
    """Returns (stored_ref, size). Cloudinary ref = 'resource_type|public_id|url'; local ref = filename."""
    data = f.read(); size = len(data)
    if CLOUD:
        buf = io.BytesIO(data); buf.name = secure_filename(f.filename) or "file"
        r = cloudinary.uploader.upload(buf, resource_type="auto", folder="classroom_hub",
                                       use_filename=True, unique_filename=True)
        return f"{r['resource_type']}|{r['public_id']}|{r['secure_url']}", size
    name = uuid.uuid4().hex[:10] + "_" + secure_filename(f.filename)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(os.path.join(UPLOAD_DIR, name), "wb") as out:
        out.write(data)
    return name, size

def store_delete(stored):
    try:
        if "|" in stored:
            rt, pid, _ = stored.split("|", 2)
            cloudinary.uploader.destroy(pid, resource_type=rt, invalidate=True)
        else:
            os.remove(os.path.join(UPLOAD_DIR, stored))
    except Exception:
        pass

def file_url(stored):
    return stored.split("|", 2)[2] if "|" in stored else url_for("media", name=stored)

@app.route("/media/<path:name>")
def media(name):
    return send_from_directory(UPLOAD_DIR, name)

def word(n):
    n = n.strip()
    if n.lower().endswith("zes"): return n[:-2]
    if n.lower().endswith("ies"): return n[:-3] + "y"
    return n[:-1] if n.lower().endswith("s") and len(n) > 3 else n

def new_part(name, n=1, label=None):
    return dict(id=uuid.uuid4().hex[:6], label=label or f"{word(name)} {n}", max=100.0)

def parse_scheme(txt, old=None):
    """'Quizzes: 20' or 'Exam: 35 | Long Test, Periodical Test'. Keeps existing parts of same-named components."""
    old = {c["name"].lower(): c for c in (old or [])}; out = []
    for line in txt.splitlines():
        m = re.match(r"\s*(.+?)\s*[:=]\s*(\d+(?:\.\d+)?)\s*%?\s*(?:\|\s*(.+?))?\s*$", line)
        if not m: continue
        name, w, labels = m.group(1), float(m.group(2)), m.group(3)
        if name.lower() in old:
            c = old[name.lower()]; c["name"], c["weight"] = name, w
        else:
            ls = [x.strip() for x in labels.split(",") if x.strip()] if labels else []
            c = dict(name=name, weight=w, parts=[new_part(name, i + 1, l) for i, l in enumerate(ls)] or [new_part(name)])
        out.append(c)
    return out or [dict(name="Total", weight=100.0, parts=[new_part("Total")])]

def ago(ts):
    s = (dt.datetime.now() - dt.datetime.fromisoformat(ts)).total_seconds()
    for u, n in (("day", 86400), ("hour", 3600), ("min", 60)):
        if s >= n:
            k = int(s // n)
            return f"{k} {u}{'s' if k > 1 else ''} ago"
    return "just now"

def size_fmt(b):
    for u in ("B", "KB", "MB", "GB"):
        if b < 1024 or u == "GB":
            return f"{b:.0f} {u}" if u == "B" else f"{b:.1f} {u}"
        b /= 1024

@app.context_processor
def inject():
    s = cfg()
    return dict(S=s, ago=ago, size_fmt=size_fmt, file_url=file_url,
                unread=one("SELECT COUNT(*) c FROM activity WHERE kind='notif' AND is_read=0")["c"],
                avatar=file_url(s["avatar"]) if s["avatar"] else None)

def back(default="dashboard", **kw):
    return redirect(request.referrer or url_for(default, **kw))

# ---------------------------------------------------------------- dashboard
def ungraded():
    t = 0
    for s in q("SELECT id,scheme FROM sections WHERE archived=0"):
        n = one("SELECT COUNT(*) c FROM students WHERE section_id=:i", i=s["id"])["c"]
        got = one("SELECT COUNT(*) c FROM scores sc JOIN students st ON st.id=sc.student_id "
                  "WHERE st.section_id=:i", i=s["id"])["c"]
        t += max(0, n * sum(len(c["parts"]) for c in json.loads(s["scheme"])) - got)
    return t

@app.route("/")
def dashboard():
    today = dt.date.today()
    start = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    days = [start + dt.timedelta(i) for i in range(7)]
    evs = q("SELECT * FROM events WHERE day>=:a AND day<=:b ORDER BY time",
            a=days[0].isoformat(), b=days[6].isoformat())
    week = [dict(d=d, evs=[e for e in evs if e["day"] == d.isoformat()]) for d in days]
    stats = dict(
        students=one("SELECT COUNT(*) c FROM students st JOIN sections s ON s.id=st.section_id "
                     "WHERE s.archived=0")["c"],
        classes=one("SELECT COUNT(*) c FROM events WHERE day=:d AND kind='class'", d=today.isoformat())["c"],
        ungraded=ungraded(),
        notifs=one("SELECT COUNT(*) c FROM activity WHERE kind='notif' AND is_read=0")["c"])
    feed = q("SELECT * FROM activity WHERE kind='notif' ORDER BY id DESC LIMIT 40")
    try:
        one("SELECT 1 c"); db = f"{engine.dialect.name.upper()} online"
    except Exception:
        db = "Database offline"
    cloud = "Local storage (add Cloudinary keys to .env)"; ok = False
    if CLOUD:
        try:
            import cloudinary.api
            cloudinary.api.ping(); cloud, ok = f"Connected to Cloudinary ({cloudinary.config().cloud_name})", True
        except Exception:
            cloud = "Cloudinary unreachable - check your keys"
    links = [l.split("|", 1) for l in cfg()["links"].splitlines() if "|" in l]
    return render_template("dash.html", week=week, today=today, stats=stats, feed=feed,
                           db=db, cloud=cloud, cloud_ok=ok, links=links)

@app.post("/events/add")
def event_add():
    ex("INSERT INTO events(title,day,time,kind) VALUES(:t,:d,:m,:k)", t=request.form["title"],
       d=request.form["day"], m=request.form.get("time") or "08:00", k=request.form.get("kind", "class"))
    flash("Event added."); return back()

@app.post("/events/delete/<int:i>")
def event_del(i):
    ex("DELETE FROM events WHERE id=:i", i=i); flash("Event deleted."); return back()

@app.post("/events/delete-many")
def event_del_many():
    ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
    with engine.begin() as c:
        for i in ids:
            c.execute(text("DELETE FROM events WHERE id=:i"), dict(i=i))
    flash(f"{len(ids)} schedule entries deleted."); return back()

# ---------------------------------------------------------------- lesson plans (drive)
ORDER = {"name": "name", "date": "created DESC", "size": "size DESC", "type": "kind, name"}

@app.route("/plans")
def plans():
    f = request.args.get("f", type=int)
    sort = request.args.get("s", "name"); view = request.args.get("v", "grid")
    fo = q("SELECT * FROM folders WHERE parent_id=:f ORDER BY name", f=f) if f else \
        q("SELECT * FROM folders WHERE parent_id IS NULL ORDER BY name")
    fi = q(f"SELECT * FROM files WHERE folder_id=:f ORDER BY {ORDER.get(sort, 'name')}", f=f) if f else \
        q(f"SELECT * FROM files WHERE folder_id IS NULL ORDER BY {ORDER.get(sort, 'name')}")
    cur = one("SELECT * FROM folders WHERE id=:f", f=f) if f else None
    events = q("SELECT * FROM events WHERE day>=:d ORDER BY day,time LIMIT 300", d=dt.date.today().isoformat())
    return render_template("plans.html", folders=fo, files=fi, cur=cur, f=f, sort=sort, view=view,
                           allf=q("SELECT * FROM folders ORDER BY name"), events=events)

def fid():
    return int(request.form.get("f") or 0) or None

@app.post("/plans/upload")
def upload():
    n = 0
    for f in request.files.getlist("files"):
        if f.filename:
            stored, size = store_save(f)
            ext = f.filename.rsplit(".", 1)[-1].upper()[:10] if "." in f.filename else "FILE"
            ex("INSERT INTO files(folder_id,name,stored,size,kind,created) VALUES(:f,:n,:s,:z,:k,:c)",
               f=fid(), n=f.filename, s=stored, z=size, k=ext, c=now()); n += 1
    if n: log(f"{n} file(s) uploaded to Lesson Plans.")
    flash(f"{n} file(s) uploaded."); return back()

@app.post("/plans/folder")
def folder_new():
    ex("INSERT INTO folders(name,parent_id) VALUES(:n,:p)", n=request.form["name"].strip() or "New folder", p=fid())
    return back()

@app.post("/plans/move/<int:i>")
def file_move(i):
    ex("UPDATE files SET folder_id=:f WHERE id=:i", f=int(request.form["to"] or 0) or None, i=i)
    return back()

@app.post("/plans/rename/<kind>/<int:i>")
def rename(kind, i):
    ex("UPDATE " + ("folders" if kind == "folder" else "files") + " SET name=:n WHERE id=:i",
       n=request.form["name"], i=i)
    return back()

def rm_folder(i):
    for c in q("SELECT id FROM folders WHERE parent_id=:i", i=i):
        rm_folder(c["id"])
    for f in q("SELECT stored FROM files WHERE folder_id=:i", i=i):
        store_delete(f["stored"])
    ex("DELETE FROM files WHERE folder_id=:i", i=i)
    ex("DELETE FROM folders WHERE id=:i", i=i)

@app.post("/plans/delete/<kind>/<int:i>")
def plan_delete(kind, i):
    if kind == "folder":
        rm_folder(i)
    else:
        r = one("SELECT stored FROM files WHERE id=:i", i=i)
        if r: store_delete(r["stored"])
        ex("DELETE FROM files WHERE id=:i", i=i)
    flash("Deleted."); return back("plans")

@app.post("/plans/delete-many")
def plan_delete_many():
    for v in request.form.getlist("ids"):
        kind, _, i = v.partition(":")
        if not i.isdigit(): continue
        i = int(i)
        if kind == "d":
            rm_folder(i)
        else:
            r = one("SELECT stored FROM files WHERE id=:i", i=i)
            if r: store_delete(r["stored"])
            ex("DELETE FROM files WHERE id=:i", i=i)
    flash("Selected items deleted."); return back("plans")

WD = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

@app.post("/plans/schedule")
def schedule_paste():
    today = dt.date.today(); monday = today - dt.timedelta(days=today.weekday())
    weeks = max(1, min(40, int(request.form.get("weeks") or 1))); n = 0
    for line in request.form["text"].splitlines():
        m = re.match(r"\s*(\S+)\s+(\d{1,2}:\d{2})\s+(.+)", line)
        if not m: continue
        d, t, title = m.groups()
        try:
            base = monday + dt.timedelta(WD.index(d[:3].lower())) if d[:3].lower() in WD \
                else dt.date.fromisoformat(d)
        except ValueError:
            continue
        for w in range(weeks):
            ex("INSERT INTO events(title,day,time,kind) VALUES(:t,:d,:m,:k)", t=title.strip(),
               d=(base + dt.timedelta(weeks=w)).isoformat(), m=t.zfill(5), k=request.form.get("kind", "class")); n += 1
    if n: log(f"{n} schedule entries added.")
    flash(f"{n} schedule entries added." if n else "No lines understood. Use: Mon 08:00 Math 7"); return back()

# ---------------------------------------------------------------- grades
@app.route("/grades")
def grades():
    secs = q("SELECT * FROM sections WHERE archived=0 ORDER BY name")
    for s in secs:
        s["n"] = one("SELECT COUNT(*) c FROM students WHERE section_id=:i", i=s["id"])["c"]
        s["scheme_l"] = json.loads(s["scheme"])
    return render_template("grades.html", secs=secs,
                           binned=one("SELECT COUNT(*) c FROM sections WHERE archived=1")["c"])

@app.post("/grades/new")
def section_new():
    i = ex("INSERT INTO sections(name,subject,scheme,archived) VALUES(:n,:s,:c,0)", n=request.form["name"],
           s=request.form.get("subject", ""), c=json.dumps(parse_scheme(cfg()["scheme"])))
    log(f"Section {request.form['name']} created.")
    return redirect(url_for("section", sid=i))

def save_scheme(sid, scheme):
    ex("UPDATE sections SET scheme=:c WHERE id=:i", c=json.dumps(scheme), i=sid)

@app.route("/grades/<int:sid>", methods=["GET", "POST"])
def section(sid):
    sec = one("SELECT * FROM sections WHERE id=:i", i=sid) or abort(404)
    scheme = json.loads(sec["scheme"])
    if request.method == "POST":
        act = request.form["act"]
        if act == "scores":
            parts = {p["id"]: p for c in scheme for p in c["parts"]}
            with engine.begin() as c:
                for k, v in request.form.items():
                    m = re.fullmatch(r"m_(\w+)", k)
                    if m and m[1] in parts:
                        try: parts[m[1]]["max"] = max(1.0, float(v))
                        except ValueError: pass
                    m = re.fullmatch(r"s_(\d+)_(\w+)", k)
                    if m and m[2] in parts:
                        c.execute(text("DELETE FROM scores WHERE student_id=:s AND comp=:c"), dict(s=int(m[1]), c=m[2]))
                        try: c.execute(text("INSERT INTO scores(student_id,comp,val) VALUES(:s,:c,:v)"),
                                       dict(s=int(m[1]), c=m[2], v=str(float(v))))
                        except ValueError: pass
            save_scheme(sid, scheme); log(f"Grades updated for {sec['name']}."); flash("Grades saved.")
        elif act == "scheme":
            ex("UPDATE sections SET name=:n, subject=:s WHERE id=:i", n=request.form["name"], s=request.form["subject"], i=sid)
            save_scheme(sid, parse_scheme(request.form["scheme"], scheme)); flash("Grading system updated.")
        elif act == "add":
            for nm in request.form["names"].splitlines():
                if nm.strip():
                    ex("INSERT INTO students(section_id,name) VALUES(:s,:n)", s=sid, n=nm.strip())
        return redirect(url_for("section", sid=sid))
    studs = q("SELECT * FROM students WHERE section_id=:i ORDER BY name", i=sid)
    sc = {(r["student_id"], r["comp"]): float(r["val"]) for r in q(
        "SELECT sc.* FROM scores sc JOIN students s ON s.id=sc.student_id WHERE s.section_id=:i", i=sid)}
    rows = []
    for st in studs:
        cells = []; num = den = 0
        for c in scheme:
            got = [(sc[(st["id"], p["id"])], p["max"]) for p in c["parts"] if (st["id"], p["id"]) in sc]
            pct = round(sum(g for g, m in got) / sum(m for g, m in got) * 100, 1) if got else None
            cells.append(dict(vals=[sc.get((st["id"], p["id"])) for p in c["parts"]], pct=pct))
            if pct is not None: num += pct * c["weight"]; den += c["weight"]
        rows.append(dict(id=st["id"], name=st["name"], cells=cells, final=round(num / den, 1) if den else None))
    return render_template("section.html", sec=sec, scheme=scheme, rows=rows,
                           scheme_txt="\n".join(f"{c['name']}: {c['weight']:g}" for c in scheme),
                           total=sum(c["weight"] for c in scheme))

@app.post("/grades/<int:sid>/part/<int:ci>/<act>")
def part_edit(sid, ci, act):
    sec = one("SELECT * FROM sections WHERE id=:i", i=sid) or abort(404)
    scheme = json.loads(sec["scheme"]); c = scheme[ci]
    if act == "add":
        c["parts"].append(new_part(c["name"], len(c["parts"]) + 1))
    elif len(c["parts"]) > 1:
        ex("DELETE FROM scores WHERE comp=:c", c=c["parts"].pop()["id"])
    else:
        flash("Each component needs at least one item.")
    save_scheme(sid, scheme)
    return redirect(url_for("section", sid=sid))

@app.post("/grades/<int:sid>/student/<int:i>/delete")
def student_del(sid, i):
    ex("DELETE FROM scores WHERE student_id=:i", i=i); ex("DELETE FROM students WHERE id=:i", i=i)
    return back()

@app.post("/grades/<int:sid>/complete")
def complete(sid):
    ex("UPDATE sections SET archived=1, completed_on=:d WHERE id=:i", d=dt.date.today().isoformat(), i=sid)
    log("A section was completed and moved to the Bin."); flash("Section completed and moved to the Bin.")
    return redirect(url_for("grades"))

@app.route("/bin")
def bin_():
    secs = q("SELECT * FROM sections WHERE archived=1 ORDER BY completed_on DESC")
    for s in secs:
        s["n"] = one("SELECT COUNT(*) c FROM students WHERE section_id=:i", i=s["id"])["c"]
    return render_template("bin.html", secs=secs)

@app.post("/bin/restore/<int:sid>")
def restore(sid):
    ex("UPDATE sections SET archived=0, completed_on=NULL WHERE id=:i", i=sid)
    flash("Section restored."); return back("bin_")

@app.post("/bin/purge/<int:sid>")
def purge(sid):
    ex("DELETE FROM scores WHERE student_id IN (SELECT id FROM students WHERE section_id=:i)", i=sid)
    ex("DELETE FROM students WHERE section_id=:i", i=sid); ex("DELETE FROM sections WHERE id=:i", i=sid)
    flash("Section permanently deleted."); return back("bin_")

# ---------------------------------------------------------------- feed / notifications / settings
@app.route("/notifications", methods=["GET", "POST"])
def notifs():
    if request.method == "POST":
        ex("UPDATE activity SET is_read=1 WHERE kind='notif'"); return redirect(url_for("notifs"))
    return render_template("notifs.html", items=q("SELECT * FROM activity WHERE kind='notif' ORDER BY id DESC LIMIT 100"))

@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        for k in DEFAULTS:
            if k.startswith("w_"):
                put(k, "1" if request.form.get(k) else "0")
            elif k != "avatar" and k in request.form:
                put(k, request.form[k])
        a = request.files.get("avatar")
        if a and a.filename:
            put("avatar", store_save(a)[0])
        flash("Settings saved."); return redirect(url_for("settings"))
    return render_template("settings.html")

@app.post("/settings/reset")
def reset():
    ex("DELETE FROM settings"); flash("Settings reset to defaults."); return redirect(url_for("settings"))

# ---------------------------------------------------------------- templates
BASE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>{{S.app_name}}</title>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel=stylesheet>
<style>
:root{--ac:{{S.accent}};--sb:{{S.sidebar}};--bg:{{S.bg}};--ink:#0f2236;--mut:#62788c;--line:#e4edf3;--ac2:color-mix(in srgb,var(--ac),#3fc1d4 55%)}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;font:15px 'Plus Jakarta Sans',system-ui,sans-serif;color:var(--ink);display:flex;min-height:100vh;
background:radial-gradient(900px 500px at 85% -10%,#ffffffd0,transparent),radial-gradient(700px 500px at 10% 110%,#c6e3f2aa,transparent),var(--bg)}
aside{width:262px;flex:none;background:linear-gradient(190deg,var(--sb),#08162b);color:#fff;padding:22px 14px;position:sticky;top:0;height:100vh;overflow:hidden}
aside::after{content:"";position:absolute;width:300px;height:300px;border-radius:50%;left:-120px;bottom:-110px;background:radial-gradient(circle,var(--ac2),transparent 70%);opacity:.35}
aside h1{font-size:18px;font-weight:800;margin:2px 10px 28px;line-height:1.25;letter-spacing:-.01em}
aside a{display:flex;gap:12px;align-items:center;padding:12px 14px;margin:3px 0;border-radius:12px;color:#c9d8e8;text-decoration:none;font-weight:500;position:relative;z-index:1;transition:transform .2s,background .2s,color .2s}
aside a:hover{background:#ffffff14;color:#fff;transform:translateX(4px)}
aside a.on{background:linear-gradient(135deg,var(--ac),var(--ac2));color:#fff;box-shadow:0 8px 20px -6px var(--ac2)}
.badge{margin-left:auto;background:#ff5d5d;border-radius:99px;font-size:11px;font-weight:700;padding:1px 8px}
main{flex:1;min-width:0}
header{background:#ffffffc8;backdrop-filter:blur(10px);height:68px;display:flex;align-items:center;justify-content:flex-end;gap:12px;padding:0 30px;border-bottom:1px solid var(--line);font-weight:600;position:sticky;top:0;z-index:5}
header img,.av{width:42px;height:42px;border-radius:50%;object-fit:cover;background:linear-gradient(135deg,var(--ac),var(--ac2));color:#fff;display:grid;place-items:center;font-weight:700;box-shadow:0 0 0 3px #fff,0 0 0 5px var(--ac2)}
header a{transition:transform .5s}header a:hover{transform:rotate(90deg)}
.pg{padding:28px 32px 40px;max-width:1500px}h2{margin:0 0 20px;font-size:28px;font-weight:800;letter-spacing:-.02em}h3{margin:0 0 14px;font-size:17px;font-weight:700}
.card{background:#fff;border-radius:20px;padding:20px;box-shadow:0 1px 2px #0f22360a,0 14px 34px -16px #0f223633;transition:transform .25s,box-shadow .25s}
.card:hover{box-shadow:0 1px 2px #0f22360a,0 20px 40px -16px #0f223644}
.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.sp{margin-left:auto}
.g4{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:18px;margin-bottom:20px}
.g3{display:grid;grid-template-columns:1.6fr 1.1fr .9fr;gap:18px;align-items:start}
.stat{display:flex;gap:14px;align-items:center}.stat:hover{transform:translateY(-4px)}
.stat b{display:block;font-size:32px;font-weight:800;line-height:1.1}.stat span{color:var(--mut);font-size:13px;font-weight:500}
.ic{width:52px;height:52px;border-radius:15px;display:grid;place-items:center;font-size:23px;font-style:normal}
.b1{background:#dff1fb}.b2{background:#dff5e9}.b3{background:#fde8e5}.b4{background:#ebe8fb}
.btn{border:0;background:#e4f0f6;color:var(--ac);font:600 14px 'Plus Jakarta Sans';padding:10px 16px;border-radius:12px;cursor:pointer;text-decoration:none;display:inline-block;transition:transform .15s,box-shadow .2s,filter .2s}
.btn:hover{transform:translateY(-2px);filter:brightness(.97)}.btn:active{transform:scale(.96)}
.btn.p{background:linear-gradient(135deg,var(--ac),var(--ac2));color:#fff;box-shadow:0 8px 18px -8px var(--ac)}
.btn.d{background:#fde8e8;color:#c42b2b}.btn.s{padding:5px 10px;font-size:13px;border-radius:9px}
input,select,textarea{font:inherit;padding:10px 12px;border:1.5px solid #d3e0e9;border-radius:12px;background:#fff;max-width:100%;transition:border-color .2s,box-shadow .2s}
input:focus,select:focus,textarea:focus{outline:0;border-color:var(--ac2);box-shadow:0 0 0 4px #3fc1d433}
textarea{width:100%;min-height:110px}label{display:block;font-weight:600;margin:12px 0 4px}
.cal{display:grid;grid-template-columns:repeat(7,1fr);gap:1px;background:var(--line);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.cal>div{background:#fff;min-height:135px;padding:7px;font-size:12px}.cal .t{background:#eaf6fb}.cal small{color:var(--mut);font-weight:700}
.cal .t small::before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;background:#ff5d5d;margin-right:5px;animation:pulse 1.8s infinite}
.chip{display:block;background:linear-gradient(135deg,var(--ac),var(--ac2));color:#fff;border-radius:7px;padding:3px 7px;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;transition:transform .2s}
.chip:hover{transform:scale(1.04)}.chip.event{background:#d3e8f3;color:var(--ac)}
.dg{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start}
.dg>.card,.rc>.card{display:flex;flex-direction:column;min-height:0;min-width:0}
.sch{height:500px}.rc{display:flex;flex-direction:column;gap:18px;min-width:0;height:500px}
.act{flex:0 0 300px}.rq{flex:1 1 0}
.dg .body{flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;padding-right:6px}
.dg .body>*{flex:none}.dg .body>.cal{flex:1 0 auto;min-width:780px}
.dg .feed div{word-break:break-word}
.body::-webkit-scrollbar{width:8px;height:8px}.body::-webkit-scrollbar-thumb{background:#c4d6e2;border-radius:9px}.body::-webkit-scrollbar-thumb:hover{background:#9fbbcd}
.body{scrollbar-width:thin;scrollbar-color:#c4d6e2 transparent}
.feed::-webkit-scrollbar,.sc::-webkit-scrollbar{width:7px;height:8px}.feed::-webkit-scrollbar-thumb,.sc::-webkit-scrollbar-thumb{background:#c4d6e2;border-radius:9px}
.feed{scrollbar-width:thin;scrollbar-color:#c4d6e2 transparent}
.feed div{padding:11px 0;border-bottom:1px solid var(--line)}.feed small{color:var(--mut)}
.items{display:grid;grid-template-columns:repeat(auto-fill,minmax(215px,1fr));gap:16px}.items.list{grid-template-columns:1fr}
.it{background:#fff;border:1px solid var(--line);border-radius:18px;padding:16px;transition:transform .25s,box-shadow .25s}
.it:hover{transform:translateY(-5px);box-shadow:0 18px 30px -16px #0f223644}.it .ic{font-size:30px;width:auto;height:auto;display:block}
.it a.nm{font-weight:700;color:var(--ink);text-decoration:none;word-break:break-word}.it small{display:block;color:var(--mut);margin:4px 0 8px}
table{width:100%;border-collapse:collapse}th,td{padding:9px;border-bottom:1px solid var(--line);text-align:left}tbody tr{transition:background .15s}tbody tr:hover{background:#f3f9fc}
.sc{overflow-x:auto}.gb th{text-align:center;vertical-align:bottom;font-size:13px}.gb th.grp{background:#edf6fa;border-left:3px solid #fff}
.gb td:not(:first-child){text-align:center}.gb td input[type=number]{width:72px;text-align:center}
.mx{width:62px!important;padding:3px 5px!important;font-size:12px!important;margin-top:3px}.pc{background:#f3f9fc;font-weight:700}
.pill{display:inline-block;padding:3px 11px;border-radius:99px;font-weight:700;background:#dff5e9;color:#16783f}.pill.low{background:#fde8e5;color:#c0392b}
.pm{display:inline-flex;gap:4px;margin-left:8px}.pm .btn{width:26px;height:26px;padding:0;line-height:26px;text-align:center}
.ok{color:#188a46;font-weight:600}.flash{background:#dff5e9;color:#14683a;padding:12px 16px;border-radius:14px;margin-bottom:16px;font-weight:600}
#m{position:fixed;inset:0;background:#0a1a2e88;backdrop-filter:blur(3px);display:none;place-items:center;z-index:99}#m.open{display:grid}#m .card{max-width:430px;width:92%}
details summary{cursor:pointer;list-style:none}.crumb a{color:var(--ac);font-weight:700;text-decoration:none}
.it{position:relative}.it .pk{position:absolute;top:14px;right:14px;width:18px;height:18px;padding:0;cursor:pointer}
@keyframes up{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
@keyframes pop{from{opacity:0;transform:scale(.93)}to{opacity:1;transform:none}}
@keyframes slide{from{opacity:0;transform:translateX(-16px)}to{opacity:1;transform:none}}
@keyframes pulse{50%{box-shadow:0 0 0 6px #ff5d5d00,0 0 0 0 #ff5d5d88;opacity:.5}}
.pg>*{animation:up .6s cubic-bezier(.2,.7,.2,1) both}.pg>:nth-child(2){animation-delay:.07s}.pg>:nth-child(3){animation-delay:.14s}.pg>:nth-child(4){animation-delay:.21s}.pg>:nth-child(n+5){animation-delay:.28s}
.g4>*,.items>*{animation:pop .5s cubic-bezier(.2,.7,.2,1) both}
.g4>:nth-child(2),.items>:nth-child(2){animation-delay:.08s}.g4>:nth-child(3),.items>:nth-child(3){animation-delay:.16s}.g4>:nth-child(4),.items>:nth-child(4){animation-delay:.24s}.items>:nth-child(n+5){animation-delay:.3s}
aside a{animation:slide .5s both}aside a:nth-child(3){animation-delay:.05s}aside a:nth-child(4){animation-delay:.1s}aside a:nth-child(5){animation-delay:.15s}aside a:nth-child(6){animation-delay:.2s}
#m.open .card{animation:pop .25s}
@media(max-width:900px){body{flex-direction:column}aside{width:100%;height:auto;position:static}.g3,.dg{grid-template-columns:1fr}.rc{height:auto}.sch,.act{height:420px;flex:none}.rq{flex:none;max-height:300px}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body>
<aside><h1>🖥 {{S.app_name}}</h1>
{% for ep,ic,k in [('dashboard','▦','lbl_dashboard'),('plans','📘','lbl_plans'),('grades','📊','lbl_grades'),('notifs','🔔','lbl_notifs'),('settings','⚙','lbl_settings')] %}
<a href="{{url_for(ep)}}" class="{{'on' if request.endpoint==ep or (ep=='grades' and request.endpoint in ('section','bin_'))}}">{{ic}} {{S[k]}}{% if ep=='notifs' and unread %}<span class=badge>{{unread}}</span>{% endif %}</a>
{% endfor %}</aside>
<main><header>{% if avatar %}<img src="{{avatar}}" alt="">{% else %}<span class=av>{{S.teacher[:1]}}</span>{% endif %}<span style="line-height:1.25">{{S.teacher}}<small style="display:block;font-weight:500;color:var(--mut);font-size:12px">{{S.school}}</small></span><a href="{{url_for('settings')}}" style="text-decoration:none">⚙</a></header>
<div class=pg>{% for m in get_flashed_messages() %}<div class=flash>{{m}}</div>{% endfor %}{% block c %}{% endblock %}</div></main>
<div id=m><form class=card id=mf method=post><h3>Are you sure?</h3><p id=mt></p>
<label style="font-weight:400"><input type=checkbox id=chk> Yes, I understand this can't be undone.</label>
<div class=row style="margin-top:16px"><button class="btn d" id=ok disabled>Delete</button><button type=button class=btn id=no>Cancel</button></div></form></div>
<script>
const m=document.getElementById('m'),f=document.getElementById('mf'),ok=document.getElementById('ok'),chk=document.getElementById('chk');
document.querySelectorAll('[data-del]').forEach(b=>b.onclick=e=>{e.preventDefault();f.querySelectorAll('input[name=ids]').forEach(x=>x.remove());
let msg=b.dataset.msg||('Delete "'+b.dataset.name+'"?');
if(b.dataset.collect){const c=[...document.querySelectorAll('.'+b.dataset.collect+':checked')];if(!c.length){alert('Select at least one entry first.');return}
c.forEach(x=>{const i=document.createElement('input');i.type='hidden';i.name='ids';i.value=x.value;f.appendChild(i)});const u=(b.dataset.unit||'entry|entries').split('|');msg='Delete '+c.length+' selected '+u[c.length>1?1:0]+'?'+(b.dataset.extra||'')}
f.action=b.dataset.del;document.getElementById('mt').textContent=msg;chk.checked=false;ok.disabled=true;m.classList.add('open')});
chk.onchange=()=>ok.disabled=!chk.checked;document.getElementById('no').onclick=()=>m.classList.remove('open');
document.querySelectorAll('[data-n]').forEach(el=>{const t=+el.dataset.n;let s=null;const st=ts=>{s=s||ts;const p=Math.min((ts-s)/900,1);
el.textContent=Math.round(t*(1-Math.pow(1-p,3)));if(p<1)requestAnimationFrame(st)};requestAnimationFrame(st)});
</script></body></html>"""

DASH = """{% extends 'base.html' %}{% block c %}
<div class=row><h2>{{S.lbl_dashboard}} Overview</h2><a class="btn sp" href="{{url_for('settings')}}#layout">Customize layout</a></div>
<div class=g4>
<div class="card stat"><i class="ic b1">👥</i><div><span>Total Students</span><b data-n="{{stats.students}}">0</b></div></div>
<div class="card stat"><i class="ic b2">📅</i><div><span>Classes Today</span><b data-n="{{stats.classes}}">0</b></div></div>
<div class="card stat"><i class="ic b3">📝</i><div><span>Ungraded Assignments</span><b data-n="{{stats.ungraded}}">0</b></div></div>
<div class="card stat"><i class="ic b4">🔔</i><div><span>Unread Notifications</span><b data-n="{{stats.notifs}}">0</b></div></div></div>
<div class=dg>
{% if S.w_schedule=='1' %}<div class="card sch"><div class=row><h3>Upcoming Schedule</h3>
<details class=sp style="position:relative"><summary class="btn p">＋ Add new event</summary>
<form method=post action="{{url_for('event_add')}}" class=card style="position:absolute;right:0;top:46px;z-index:20;width:290px;box-shadow:0 8px 30px #0003">
<input name=title placeholder="Title" required><br><br><input type=date name=day value="{{today}}" required> <input type=time name=time value="08:00"><br><br>
<select name=kind><option value=class>Class</option><option value=event>Event</option></select> <button class="btn p">Save</button></form></details></div>
<div class=body><div class=cal>{% for w in week %}<div class="{{'t' if w.d==today}}"><small>{{w.d.strftime('%a %d')}}</small>
{% for e in w.evs %}<span class="chip {{e.kind}}" title="{{e.title}}">{{e.time}} {{e.title}}</span>{% endfor %}</div>{% endfor %}</div></div></div>{% endif %}
<div class=rc>
{% if S.w_activity=='1' %}<div class="card act"><h3>Activity Stream</h3><div class="body feed">
{% for a in feed %}<div>{{a.body}}<br><small>{{ago(a.ts)}}</small></div>{% else %}<p>No activity yet.</p>{% endfor %}</div></div>{% endif %}
{% if S.w_resources=='1' %}<div class="card rq"><h3>Resource Quick Access</h3><div class=body>
<p><a class="btn p" style="display:block;text-align:center" href="{{url_for('plans')}}">📄 Open {{S.lbl_plans}}</a></p>
<p><a class=btn style="display:block;text-align:center" href="{{url_for('grades')}}">📊 Open {{S.lbl_grades}}</a></p>
{% for t,u in links %}<p><a class=btn style="display:block;text-align:center" target=_blank href="{{u}}">🔗 {{t}}</a></p>{% endfor %}</div></div>{% endif %}
</div></div>
{% if S.w_status=='1' %}<div class=card style="margin-top:18px"><h3>System Status</h3><div class=row style="gap:40px">
<div>☁ <b>Cloud Sync:</b> <span class="{{'ok' if cloud_ok}}">{{cloud}}</span></div><div>🗄 <b>Database:</b> {{db}}</div></div></div>{% endif %}
{% endblock %}"""

PLANS = """{% extends 'base.html' %}{% block c %}
<h2>{{S.lbl_plans}}</h2>
<div class=card style="margin-bottom:16px"><div class="row crumb"><a href="{{url_for('plans')}}">My Files</a>
{% if cur %}/ <b>{{cur.name}}</b>{% endif %}
<form method=post action="{{url_for('upload')}}" enctype=multipart/form-data class="row sp"><input type=hidden name=f value="{{f or ''}}">
<input type=file name=files multiple required><button class="btn p">⬆ Upload</button></form></div>
<div class=row style="margin-top:12px">
<form method=post action="{{url_for('folder_new')}}" class=row><input type=hidden name=f value="{{f or ''}}"><input name=name placeholder="New folder name" required><button class=btn>📁 Create folder</button></form>
<form class="row sp" method=get><input type=hidden name=f value="{{f or ''}}">Sort
<select name=s onchange=this.form.submit()>{% for k in ['name','date','size','type'] %}<option {{'selected' if sort==k}}>{{k}}</option>{% endfor %}</select>
<select name=v onchange=this.form.submit()><option {{'selected' if view=='grid'}}>grid</option><option {{'selected' if view=='list'}}>list</option></select></form></div></div>
{% if folders or files %}<div class=row style="margin-bottom:12px"><label style="display:flex;gap:8px;align-items:center;margin:0;font-weight:600;cursor:pointer"><input type=checkbox id=pall onchange="document.querySelectorAll('.plsel').forEach(x=>x.checked=this.checked);pcnt()"> Select all</label>
<button type=button class="btn d s" data-del="{{url_for('plan_delete_many')}}" data-collect=plsel data-unit="item|items" data-extra=" Folders are deleted with everything inside.">🗑 Delete selected <span id=pn></span></button></div>{% endif %}
<div class="items {{view if view=='list'}}">
{% for d in folders %}<div class=it><input type=checkbox class="plsel pk" value="d:{{d.id}}" onchange="pcnt()"><div class=ic>📁</div><a class=nm href="{{url_for('plans',f=d.id,s=sort,v=view)}}">{{d.name}}</a><small>Folder</small>
<form method=post action="{{url_for('rename',kind='folder',i=d.id)}}" class=row><input name=name value="{{d.name}}" style="width:110px"><button class="btn s">Rename</button>
<button class="btn d s" data-del="{{url_for('plan_delete',kind='folder',i=d.id)}}" data-msg='Delete folder "{{d.name}}" and everything inside it?'>🗑</button></form></div>{% endfor %}
{% for x in files %}<div class=it><input type=checkbox class="plsel pk" value="f:{{x.id}}" onchange="pcnt()"><div class=ic>📄</div><a class=nm target=_blank href="{{file_url(x.stored)}}">{{x.name}}</a>
<small>{{x.kind}} · {{size_fmt(x.size)}} · {{x.created[:10]}}</small>
<div class=row><form method=post action="{{url_for('file_move',i=x.id)}}"><select name=to onchange=this.form.submit()><option value="">Move to…</option><option value="">My Files (root)</option>
{% for d in allf %}<option value="{{d.id}}">{{d.name}}</option>{% endfor %}</select></form>
<button class="btn d s" data-del="{{url_for('plan_delete',kind='file',i=x.id)}}" data-name="{{x.name}}">🗑 Delete</button></div></div>{% endfor %}
</div>{% if not folders and not files %}<div class=card>This folder is empty. Upload a lesson plan to begin.</div>{% endif %}
<script>function pcnt(){const c=document.querySelectorAll('.plsel:checked').length,n=document.querySelectorAll('.plsel').length,e=document.getElementById('pn'),a=document.getElementById('pall');
if(e)e.textContent=c?'('+c+')':'';if(a)a.checked=c>0&&c==n}</script>
<div class=card style="margin-top:18px"><h3>Paste your schedule</h3>
<form method=post action="{{url_for('schedule_paste')}}"><p style="color:var(--mut)">One per line: <code>Mon 08:00 Math 7</code> or <code>2026-11-03 13:30 Science 8</code></p>
<textarea name=text placeholder="Mon 08:00 Math 7&#10;Tue 10:30 Science 8&#10;Fri 13:00 Faculty meeting"></textarea>
<div class=row style="margin-top:10px">Repeat for <input type=number name=weeks value=1 min=1 max=40 style="width:70px"> week(s)
<select name=kind><option value=class>Class</option><option value=event>Event</option></select><button class="btn p">Add to schedule</button></div></form>
{% if events %}<div class=row style="margin-top:22px"><h3 style="margin:0">Upcoming entries <small style="color:var(--mut);font-weight:500">({{events|length}})</small></h3>
<label class=sp style="display:flex;gap:8px;align-items:center;margin:0;font-weight:600;cursor:pointer"><input type=checkbox id=evall onchange="document.querySelectorAll('.evsel').forEach(x=>x.checked=this.checked);cnt()"> Select all</label>
<button type=button id=evdel class="btn d s" data-del="{{url_for('event_del_many')}}" data-collect=evsel>🗑 Delete selected <span id=evn></span></button></div>
<div style="max-height:340px;overflow:auto;margin-top:10px;border:1px solid var(--line);border-radius:12px"><table>{% for e in events %}<tr><td style="width:36px"><input type=checkbox class=evsel value="{{e.id}}" onchange="cnt()"></td>
<td>{{e.day}}</td><td>{{e.time}}</td><td>{{e.title}}</td><td>{{e.kind}}</td>
<td><button type=button class="btn d s" data-del="{{url_for('event_del',i=e.id)}}" data-name="{{e.title}}">Remove</button></td></tr>{% endfor %}</table></div>
<script>function cnt(){const c=document.querySelectorAll('.evsel:checked').length,n=document.querySelectorAll('.evsel').length;
document.getElementById('evn').textContent=c?'('+c+')':'';document.getElementById('evall').checked=c>0&&c==n}</script>{% endif %}</div>
{% endblock %}"""

GRADES = """{% extends 'base.html' %}{% block c %}
<div class=row><h2>{{S.lbl_grades}}</h2><a class="btn sp" href="{{url_for('bin_')}}">🗑 Bin ({{binned}})</a></div>
<form class="card row" method=post action="{{url_for('section_new')}}" style="margin-bottom:16px">
<input name=name placeholder="Section name (e.g. 10-Newton)" required><input name=subject placeholder="Subject"><button class="btn p">＋ Add section</button></form>
<div class=items>{% for s in secs %}<a class=it href="{{url_for('section',sid=s.id)}}" style="text-decoration:none;color:inherit">
<div class=ic>👥</div><b>{{s.name}}</b><small>{{s.subject}} · {{s.n}} students</small><small>{{s.scheme_l|map(attribute='name')|join(', ')}}</small></a>
{% else %}<div class=card>No sections yet. Add your first one above.</div>{% endfor %}</div>{% endblock %}"""

SECTION = """{% extends 'base.html' %}{% block c %}
<div class=row><h2>{{sec.name}} <small style="color:var(--mut);font-size:16px;font-weight:500">{{sec.subject}}</small></h2>
<a class="btn" href="{{url_for('grades')}}">← Sections</a>
<form method=post action="{{url_for('complete',sid=sec.id)}}" class=sp onsubmit="return confirm('Mark this section as complete and move it to the Bin? You can restore it anytime.')">
<button class="btn p">✔ Complete section</button></form></div>
{% for c in scheme %}<form id="add{{loop.index0}}" method=post action="{{url_for('part_edit',sid=sec.id,ci=loop.index0,act='add')}}"></form>{% endfor %}
<div class=card style="margin-bottom:18px"><form method=post><input type=hidden name=act value=scores><div class=sc>
<table class=gb><thead><tr><th rowspan=2 style="text-align:left">Student</th>
{% for c in scheme %}<th colspan="{{c['parts']|length+1}}" class=grp>{{c.name}} · {{'%g'|format(c.weight)}}%
<span class=pm><button form="add{{loop.index0}}" class="btn s" title="Add {{c.name}} item">＋</button>
<button type=button class="btn d s" title="Remove last" data-del="{{url_for('part_edit',sid=sec.id,ci=loop.index0,act='remove')}}" data-msg="Remove the last item of {{c.name}} and all its scores?">−</button></span></th>{% endfor %}
<th rowspan=2>Final</th><th rowspan=2></th></tr>
<tr>{% for c in scheme %}{% for p in c['parts'] %}<th>{{p.label}}<br><input class=mx type=number min=1 step=any name="m_{{p.id}}" value="{{'%g'|format(p.max)}}" title="Highest possible score"></th>{% endfor %}<th class=pc>%</th>{% endfor %}</tr></thead>
<tbody>{% for r in rows %}<tr><td style="text-align:left;font-weight:600">{{r.name}}</td>
{% for cell in r.cells %}{% set c=scheme[loop.index0] %}{% for v in cell.vals %}<td><input type=number step=any min=0 name="s_{{r.id}}_{{c['parts'][loop.index0].id}}" value="{{'' if v is none else '%g'|format(v)}}"></td>{% endfor %}<td class=pc>{{'—' if cell.pct is none else cell.pct}}</td>{% endfor %}
<td>{% if r.final is none %}—{% else %}<span class="pill {{'low' if r.final<75}}">{{r.final}}</span>{% endif %}</td>
<td><button type=button class="btn d s" data-del="{{url_for('student_del',sid=sec.id,i=r.id)}}" data-name="{{r.name}}">Remove</button></td></tr>
{% else %}<tr><td colspan=40>No students yet. Add them below.</td></tr>{% endfor %}</tbody></table></div>
<p style="color:var(--mut);font-size:13px">Type each score, and set the highest possible score under each title. A component's % = total score ÷ total possible. Blank boxes are skipped.</p>
{% if rows %}<button class="btn p">Save grades</button>{% endif %}</form></div>
<div class=g3 style="grid-template-columns:1fr 1fr">
<div class=card><h3>Add students</h3><form method=post><input type=hidden name=act value=add><textarea name=names placeholder="One name per line"></textarea><p><button class="btn p">Add</button></p></form></div>
<div class=card><h3>Grading system {% if total!=100 %}<small style="color:#c42b2b">(weights add up to {{'%g'|format(total)}}, not 100)</small>{% endif %}</h3>
<form method=post><input type=hidden name=act value=scheme><input name=name value="{{sec.name}}"> <input name=subject value="{{sec.subject}}">
<textarea name=scheme>{{scheme_txt}}</textarea><p style="color:var(--mut)">One per line: <code>Component: weight</code>. Use ＋ / − in the table to add or remove items like Quiz 4.</p><button class="btn p">Save grading system</button></form></div></div>{% endblock %}"""

BIN = """{% extends 'base.html' %}{% block c %}
<div class=row><h2>Bin — completed sections</h2><a class="btn sp" href="{{url_for('grades')}}">← Sections</a></div>
<p style="color:var(--mut)">Completed sections are kept here forever. Restore one anytime.</p>
<div class=items>{% for s in secs %}<div class=it><div class=ic>🗂</div><b>{{s.name}}</b><small>{{s.subject}} · {{s.n}} students · completed {{s.completed_on}}</small>
<div class=row><form method=post action="{{url_for('restore',sid=s.id)}}"><button class="btn p s">↩ Restore</button></form>
<button class="btn d s" data-del="{{url_for('purge',sid=s.id)}}" data-msg='Permanently delete "{{s.name}}" with all its students and grades?'>Delete forever</button></div></div>
{% else %}<div class=card>The bin is empty.</div>{% endfor %}</div>{% endblock %}"""

NOTIFS = """{% extends 'base.html' %}{% block c %}<div class=row><h2>{{S.lbl_notifs}}</h2>
<form method=post class=sp><button class=btn>Mark all as read</button></form></div>
{% for n in items %}<div class=card style="margin-bottom:10px;{{'' if n.is_read else 'border-left:4px solid var(--ac)'}}">{{n.body}}<br><small style="color:var(--mut)">{{ago(n.ts)}}</small></div>
{% else %}<div class=card>You're all caught up.</div>{% endfor %}{% endblock %}"""

SETTINGS = """{% extends 'base.html' %}{% block c %}<h2>{{S.lbl_settings}}</h2>
<form method=post enctype=multipart/form-data class=card style="max-width:760px">
<h3>Account</h3><label>Your name</label><input name=teacher value="{{S.teacher}}"><label>School</label><input name=school value="{{S.school}}">
<label>Profile photo</label><input type=file name=avatar accept="image/*">
<h3 style="margin-top:26px">Appearance</h3>
<div class=row><div><label>Accent</label><input type=color name=accent value="{{S.accent}}"></div><div><label>Sidebar</label><input type=color name=sidebar value="{{S.sidebar}}"></div>
<div><label>Background</label><input type=color name=bg value="{{S.bg}}"></div></div>
<h3 style="margin-top:26px">Rename menu items</h3><div class=row>
{% for k in ['lbl_dashboard','lbl_plans','lbl_grades','lbl_notifs','lbl_settings'] %}<input name={{k}} value="{{S[k]}}" style="width:170px">{% endfor %}</div>
<h3 id=layout style="margin-top:26px">Dashboard layout</h3><div class=row>
{% for k,t in [('w_schedule','Schedule'),('w_activity','Activity stream'),('w_resources','Quick access'),('w_status','System status')] %}
<label style="font-weight:400"><input type=checkbox name={{k}} {{'checked' if S[k]=='1'}}> {{t}}</label>{% endfor %}</div>
<label>Quick-access links (Title|URL per line)</label><textarea name=links>{{S.links}}</textarea>
<label>Default grading system for new sections</label><textarea name=scheme>{{S.scheme}}</textarea>
<p><button class="btn p">Save settings</button></p></form>
<div class=card style="max-width:760px;margin-top:16px"><h3>Connections</h3>
<p>MySQL and Cloudinary keys live in the <code>.env</code> file in the project folder. Edit it, then restart the app.</p>
<button class="btn d" data-del="{{url_for('reset')}}" data-msg="Reset all settings to defaults? Your lessons, grades and schedule are not affected.">Reset settings</button></div>{% endblock %}"""

app.jinja_env.loader = DictLoader({"base.html": BASE, "dash.html": DASH, "plans.html": PLANS,
    "grades.html": GRADES, "section.html": SECTION, "bin.html": BIN, 
    "notifs.html": NOTIFS, "settings.html": SETTINGS})

md.create_all(engine)
for _s in q("SELECT id,scheme FROM sections"):   # auto-upgrade sections saved in the old grading format
    _sc = json.loads(_s["scheme"])
    if _sc and isinstance(_sc[0], list):
        ex("UPDATE sections SET scheme=:c WHERE id=:i", i=_s["id"],
           c=json.dumps([dict(name=n, weight=float(w), parts=[new_part(n)]) for n, w in _sc]))
if not one("SELECT id FROM sections LIMIT 1") and not os.getenv("NO_DEMO"):
    log("Welcome! Add sections under Grades and upload files under Lesson Plans.")

if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", 5000)))
