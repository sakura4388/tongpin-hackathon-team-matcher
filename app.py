"""同频：Flask API、共享 SQLite 数据与前端页面。"""

import os
import secrets
import sqlite3
from pathlib import Path

from flask import Flask, g, has_request_context, jsonify, request, send_from_directory, session
from passwords import hash_password, verify_password

from matching import calculate


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DATABASE = Path(os.environ.get("APP_DB_PATH", ROOT / "instance" / "team_matcher.sqlite3"))
app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=os.environ.get("APP_SECRET_KEY") or "secret-initialized-per-process",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

_flask_wsgi = app.wsgi_app


def initialize_session_secret(environ, start_response):
    worker_env = environ.get("workers.env")
    if worker_env is not None:
        secret = getattr(worker_env, "APP_SECRET_KEY", None)
        if secret:
            app.config["SECRET_KEY"] = secret
        elif app.config["SECRET_KEY"] == "secret-initialized-per-process":
            app.config["SECRET_KEY"] = secrets.token_hex(32)
        app.config["SESSION_COOKIE_SECURE"] = bool(secret)
    elif app.config["SECRET_KEY"] == "secret-initialized-per-process":
        app.config["SECRET_KEY"] = secrets.token_hex(32)
    return _flask_wsgi(environ, start_response)


app.wsgi_app = initialize_session_secret


def db():
    if "db" not in g:
        worker_env = request.environ.get("workers.env") if has_request_context() else None
        if worker_env is not None and hasattr(worker_env, "DB"):
            from cloudflare_db import D1Connection

            g.db = D1Connection(worker_env.DB)
        else:
            DATABASE.parent.mkdir(parents=True, exist_ok=True)
            g.db = sqlite3.connect(DATABASE, timeout=10, isolation_level=None)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
            g.db.execute("PRAGMA busy_timeout = 10000")
    return g.db


@app.teardown_appcontext
def close_db(_error):
    connection = g.pop("db", None)
    if connection is not None and isinstance(connection, sqlite3.Connection):
        connection.close()


def init_db():
    db().executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            nickname TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT '参与者',
            skills TEXT NOT NULL DEFAULT '',
            interests TEXT NOT NULL DEFAULT '',
            hours INTEGER NOT NULL DEFAULT 0,
            bio TEXT NOT NULL DEFAULT '',
            contact TEXT NOT NULL DEFAULT '',
            show_contact INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY,
            owner_id INTEGER NOT NULL REFERENCES users(id),
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            needs TEXT NOT NULL,
            topics TEXT NOT NULL,
            min_hours INTEGER NOT NULL CHECK(min_hours BETWEEN 1 AND 168),
            capacity INTEGER NOT NULL CHECK(capacity BETWEEN 2 AND 20)
        );
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            status TEXT NOT NULL DEFAULT 'pending',
            UNIQUE(project_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS memberships (
            project_id INTEGER NOT NULL REFERENCES projects(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            PRIMARY KEY(project_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS project_messages (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            kind TEXT NOT NULL DEFAULT 'chat' CHECK(kind IN ('chat', 'exit')),
            content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 500),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_project_messages_project_id
            ON project_messages(project_id, id);
    """)


def error(message, status=400):
    return jsonify({"error": message}), status


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def text(value, limit):
    return value.strip()[:limit] if isinstance(value, str) else ""


def tags(value):
    if not isinstance(value, list):
        return []
    result = []
    for entry in value[:20]:
        cleaned = text(entry, 40).replace("|", " ").strip()
        if cleaned and cleaned.casefold() not in {item.casefold() for item in result}:
            result.append(cleaned)
    return result


def integer(value, low, high):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if low <= parsed <= high else None


def current_user():
    return db().execute("SELECT * FROM users WHERE id=?", (session.get("user_id"),)).fetchone()


def is_member(connection, project_id, user_id):
    return connection.execute(
        "SELECT 1 FROM memberships WHERE project_id=? AND user_id=?",
        (project_id, user_id),
    ).fetchone() is not None


def public_person(row, private=False):
    return {
        "id": row["id"], "name": row["nickname"], "role": row["role"],
        "skills": tags_from_db(row["skills"]), "interests": tags_from_db(row["interests"]),
        "hours": row["hours"], "bio": row["bio"],
        "contact": row["contact"] if private or row["show_contact"] else "",
        "showContact": bool(row["show_contact"]),
    }


def tags_from_db(value):
    return [part for part in value.split("|") if part]


@app.before_request
def protect_writes():
    if request.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        expected = session.get("csrf_token", "")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not expected or not secrets.compare_digest(expected, supplied):
            return error("页面已过期，请刷新后重试。", 403)


@app.after_request
def no_api_cache(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def home():
    worker_env = request.environ.get("workers.env")
    if worker_env is not None and hasattr(worker_env, "ASSETS"):
        return cloudflare_asset("index.html")
    return send_from_directory(WEB, "index.html")


@app.get("/web/<path:filename>")
def web_asset(filename):
    worker_env = request.environ.get("workers.env")
    if worker_env is not None and hasattr(worker_env, "ASSETS"):
        return cloudflare_asset(filename)
    return send_from_directory(WEB, filename)


def cloudflare_asset(filename):
    from flask import Response
    from pyodide.ffi import run_sync

    assets = request.environ["workers.env"].ASSETS
    asset_response = run_sync(assets.fetch(f"https://assets.local/{filename}"))
    content = run_sync(asset_response.bytes())
    content_type = asset_response.headers.get("content-type")
    headers = {"Content-Type": content_type} if content_type else {}
    return Response(content, status=asset_response.status, headers=headers)


@app.get("/api/state")
def state():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    me_row = current_user()
    me = public_person(me_row, private=True) if me_row else None
    people = [public_person(row) for row in db().execute("SELECT * FROM users ORDER BY id").fetchall()]
    projects = []
    for row in db().execute("SELECT * FROM projects ORDER BY id DESC").fetchall():
        members = [member[0] for member in db().execute(
            "SELECT user_id FROM memberships WHERE project_id=? ORDER BY rowid", (row["id"],)
        ).fetchall()]
        item = {
            "id": row["id"], "ownerId": row["owner_id"], "title": row["title"],
            "description": row["description"], "needs": tags_from_db(row["needs"]),
            "topics": tags_from_db(row["topics"]), "minHours": row["min_hours"],
            "capacity": row["capacity"], "members": members,
        }
        item["category"] = " × ".join(item["topics"][:2])
        item["match"] = calculate(me, item)
        projects.append(item)
    applications = []
    if me:
        rows = db().execute("""
            SELECT a.* FROM applications a JOIN projects p ON p.id=a.project_id
            WHERE a.user_id=? OR p.owner_id=? ORDER BY a.id DESC
        """, (me["id"], me["id"])).fetchall()
        applications = [{"id": row["id"], "projectId": row["project_id"],
                         "userId": row["user_id"], "status": row["status"]} for row in rows]
    return jsonify({"csrfToken": session["csrf_token"], "me": me, "people": people,
                    "projects": projects, "applications": applications})


@app.post("/api/register")
def register():
    data = body()
    nickname = text(data.get("nickname"), 30)
    password = data.get("password", "")
    if not nickname or not isinstance(password, str) or not 8 <= len(password) <= 128:
        return error("请输入昵称，并设置 8–128 位密码。")
    try:
        connection = db()
        password_hash = hash_password(password, cloudflare=is_d1(connection))
        cursor = connection.execute("INSERT INTO users (nickname, password_hash) VALUES (?, ?)",
                                    (nickname, password_hash))
    except sqlite3.IntegrityError:
        return error("昵称已被使用，请换一个。", 409)
    session.clear()
    session["user_id"] = cursor.lastrowid
    session["csrf_token"] = secrets.token_hex(16)
    return jsonify({"message": "注册成功，请完善名片。", "csrfToken": session["csrf_token"]})


@app.post("/api/login")
def login():
    data = body()
    connection = db()
    user = connection.execute("SELECT * FROM users WHERE nickname=?",
                              (text(data.get("nickname"), 30),)).fetchone()
    password = data.get("password", "")
    if not user or not isinstance(password, str) or not verify_password(
        user["password_hash"], password, cloudflare=is_d1(connection)
    ):
        return error("昵称或密码不正确。", 401)
    session.clear()
    session["user_id"] = user["id"]
    session["csrf_token"] = secrets.token_hex(16)
    return jsonify({"message": "登录成功。", "csrfToken": session["csrf_token"]})


@app.post("/api/logout")
def logout():
    session.clear()
    session["csrf_token"] = secrets.token_hex(16)
    return jsonify({"message": "已退出登录。", "csrfToken": session["csrf_token"]})


@app.put("/api/profile")
def profile():
    user = current_user()
    if not user:
        return error("请先登录。", 401)
    data = body()
    name, role = text(data.get("name"), 30), text(data.get("role"), 40)
    skills, interests = tags(data.get("skills")), tags(data.get("interests"))
    hours = integer(data.get("hours"), 1, 168)
    if not name or not skills or not interests or hours is None:
        return error("请填写昵称、技能、兴趣和每周可投入时间。")
    try:
        db().execute("""
            UPDATE users SET nickname=?, role=?, skills=?, interests=?, hours=?, bio=?, contact=?, show_contact=?
            WHERE id=?
        """, (name, role or "参与者", "|".join(skills), "|".join(interests), hours,
              text(data.get("bio"), 500), text(data.get("contact"), 120),
              int(data.get("showContact") is True), user["id"]))
    except sqlite3.IntegrityError:
        return error("昵称已被使用，请换一个。", 409)
    return jsonify({"message": "名片已保存。"})


@app.post("/api/projects")
def create_project():
    user = current_user()
    if not user:
        return error("请先登录。", 401)
    data = body()
    title, description = text(data.get("title"), 100), text(data.get("description"), 1000)
    needs, topics = tags(data.get("needs")), tags(data.get("topics"))
    min_hours = integer(data.get("minHours"), 1, 168)
    capacity = integer(data.get("capacity"), 2, 20)
    if not all((title, description, needs, topics, min_hours, capacity)):
        return error("请完整填写项目名称、简介、技能、方向、时间和人数。")
    connection = db()
    if is_d1(connection):
        from cloudflare_db import batch

        results = batch(connection, [
            ("""INSERT INTO projects (owner_id,title,description,needs,topics,min_hours,capacity)
                VALUES (?,?,?,?,?,?,?)""",
             (user["id"], title, description, "|".join(needs), "|".join(topics), min_hours, capacity)),
            ("""INSERT INTO memberships (project_id,user_id)
                VALUES (last_insert_rowid(), ?)""", (user["id"],)),
        ])
        return jsonify({"message": "项目已发布。", "id": results[0].meta.last_row_id}), 201
    connection.execute("BEGIN IMMEDIATE")
    try:
        cursor = connection.execute("""
            INSERT INTO projects (owner_id,title,description,needs,topics,min_hours,capacity)
            VALUES (?,?,?,?,?,?,?)
        """, (user["id"], title, description, "|".join(needs), "|".join(topics), min_hours, capacity))
        connection.execute("INSERT INTO memberships (project_id,user_id) VALUES (?,?)",
                           (cursor.lastrowid, user["id"]))
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    return jsonify({"message": "项目已发布。", "id": cursor.lastrowid}), 201


@app.post("/api/projects/<int:project_id>/apply")
def apply(project_id):
    user = current_user()
    if not user:
        return error("请先登录。", 401)
    connection = db()
    if is_d1(connection):
        cursor = connection.execute("""
            INSERT INTO applications (project_id,user_id,status)
            SELECT p.id, ?, 'pending' FROM projects p
            WHERE p.id=? AND TRUE
              AND (SELECT COUNT(*) FROM memberships WHERE project_id=p.id)<p.capacity
              AND NOT EXISTS (SELECT 1 FROM memberships WHERE project_id=p.id AND user_id=?)
            ON CONFLICT(project_id,user_id) DO UPDATE SET status='pending'
            WHERE applications.status='left'
              AND NOT EXISTS (SELECT 1 FROM memberships WHERE project_id=excluded.project_id AND user_id=excluded.user_id)
              AND (SELECT COUNT(*) FROM memberships WHERE project_id=excluded.project_id)
                  < (SELECT capacity FROM projects WHERE id=excluded.project_id)
        """, (user["id"], project_id, user["id"]))
        if cursor.rowcount:
            return jsonify({"message": "申请已发送，等待发起人处理。"}), 201
        project = connection.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            return error("项目不存在。", 404)
        return error("你已加入或申请过该项目，或者项目已满员。", 409)
    connection.execute("BEGIN IMMEDIATE")
    try:
        project = connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            connection.execute("ROLLBACK")
            return error("项目不存在。", 404)
        member = connection.execute("SELECT 1 FROM memberships WHERE project_id=? AND user_id=?",
                                    (project_id, user["id"])).fetchone()
        previous = connection.execute("SELECT * FROM applications WHERE project_id=? AND user_id=?",
                                      (project_id, user["id"])).fetchone()
        count = connection.execute("SELECT COUNT(*) FROM memberships WHERE project_id=?", (project_id,)).fetchone()[0]
        if member or (previous and previous["status"] != "left") or count >= project["capacity"]:
            connection.execute("ROLLBACK")
            return error("你已加入或申请过该项目，或者项目已满员。", 409)
        if previous:
            connection.execute("UPDATE applications SET status='pending' WHERE id=?", (previous["id"],))
        else:
            connection.execute("INSERT INTO applications (project_id,user_id) VALUES (?,?)",
                               (project_id, user["id"]))
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    return jsonify({"message": "申请已发送，等待发起人处理。"}), 201


@app.get("/api/projects/<int:project_id>/messages")
def project_messages(project_id):
    user = current_user()
    if not user:
        return error("请先登录。", 401)
    connection = db()
    if not is_member(connection, project_id, user["id"]):
        return error("只有项目正式成员可以查看讨论区。", 403)
    rows = connection.execute("""
        SELECT id,user_id,kind,content,created_at FROM project_messages
        WHERE project_id=? ORDER BY id
    """, (project_id,)).fetchall()
    return jsonify({"messages": [
        {"id": row["id"], "userId": row["user_id"], "kind": row["kind"],
         "content": row["content"], "createdAt": row["created_at"]}
        for row in rows
    ]})


@app.post("/api/projects/<int:project_id>/messages")
def send_project_message(project_id):
    user = current_user()
    if not user:
        return error("请先登录。", 401)
    raw = body().get("content")
    if not isinstance(raw, str) or not 1 <= len(raw.strip()) <= 500:
        return error("请输入 1–500 字的讨论内容。")
    connection = db()
    if is_d1(connection):
        cursor = connection.execute("""
            INSERT INTO project_messages (project_id,user_id,kind,content)
            SELECT ?,?,'chat',? WHERE EXISTS (
                SELECT 1 FROM memberships WHERE project_id=? AND user_id=?
            )
        """, (project_id, user["id"], raw.strip(), project_id, user["id"]))
        if not cursor.rowcount:
            return error("只有项目正式成员可以发言。", 403)
        return jsonify({"message": "消息已发送。"}), 201
    connection.execute("BEGIN IMMEDIATE")
    try:
        if not is_member(connection, project_id, user["id"]):
            connection.execute("ROLLBACK")
            return error("只有项目正式成员可以发言。", 403)
        connection.execute("""
            INSERT INTO project_messages (project_id,user_id,kind,content)
            VALUES (?,?,'chat',?)
        """, (project_id, user["id"], raw.strip()))
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    return jsonify({"message": "消息已发送。"}), 201


@app.post("/api/projects/<int:project_id>/leave")
def leave_project(project_id):
    user = current_user()
    if not user:
        return error("请先登录。", 401)
    raw = body().get("reason")
    if not isinstance(raw, str) or not 1 <= len(raw.strip()) <= 500:
        return error("请填写 1–500 字的退出理由。")
    connection = db()
    if is_d1(connection):
        project = connection.execute("SELECT owner_id FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            return error("项目不存在。", 404)
        if project["owner_id"] == user["id"]:
            return error("项目发起人不能从自己的项目退出。", 403)
        from cloudflare_db import batch

        results = batch(connection, [
            ("""INSERT INTO project_messages (project_id,user_id,kind,content)
                SELECT ?,?,'exit',? WHERE EXISTS (
                    SELECT 1 FROM memberships WHERE project_id=? AND user_id=?
                )""", (project_id, user["id"], raw.strip(), project_id, user["id"])),
            ("DELETE FROM memberships WHERE project_id=? AND user_id=?", (project_id, user["id"])),
            ("UPDATE applications SET status='left' WHERE project_id=? AND user_id=?",
             (project_id, user["id"])),
        ])
        if not results[0].meta.changes:
            return error("你目前不是该项目成员。", 409)
        return jsonify({"message": "已退出项目，理由已发送到小组讨论区。"})
    connection.execute("BEGIN IMMEDIATE")
    try:
        project = connection.execute("SELECT owner_id FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            connection.execute("ROLLBACK")
            return error("项目不存在。", 404)
        if project["owner_id"] == user["id"]:
            connection.execute("ROLLBACK")
            return error("项目发起人不能从自己的项目退出。", 403)
        if not is_member(connection, project_id, user["id"]):
            connection.execute("ROLLBACK")
            return error("你目前不是该项目成员。", 409)
        connection.execute("""
            INSERT INTO project_messages (project_id,user_id,kind,content)
            VALUES (?,?,'exit',?)
        """, (project_id, user["id"], raw.strip()))
        connection.execute("DELETE FROM memberships WHERE project_id=? AND user_id=?",
                           (project_id, user["id"]))
        connection.execute("""
            UPDATE applications SET status='left' WHERE project_id=? AND user_id=?
        """, (project_id, user["id"]))
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    return jsonify({"message": "已退出项目，理由已发送到小组讨论区。"})


@app.post("/api/applications/<int:application_id>/decision")
def decide(application_id):
    user = current_user()
    if not user:
        return error("请先登录。", 401)
    decision = body().get("decision")
    if decision not in {"accept", "reject"}:
        return error("无效的处理方式。")
    connection = db()
    if is_d1(connection):
        if decision == "reject":
            cursor = connection.execute("""
                UPDATE applications SET status='rejected'
                WHERE id=? AND status='pending' AND EXISTS (
                    SELECT 1 FROM projects WHERE projects.id=applications.project_id AND owner_id=?
                )
            """, (application_id, user["id"]))
            if cursor.rowcount:
                return jsonify({"message": "已拒绝申请。"})
        else:
            from cloudflare_db import batch

            results = batch(connection, [
                ("""INSERT INTO memberships (project_id,user_id)
                    SELECT a.project_id,a.user_id FROM applications a
                    JOIN projects p ON p.id=a.project_id
                    WHERE a.id=? AND a.status='pending' AND p.owner_id=?
                      AND (SELECT COUNT(*) FROM memberships WHERE project_id=a.project_id)<p.capacity
                    ON CONFLICT(project_id,user_id) DO NOTHING""",
                 (application_id, user["id"])),
                ("""UPDATE applications SET status='accepted'
                    WHERE id=? AND status='pending'
                      AND EXISTS (SELECT 1 FROM projects p WHERE p.id=applications.project_id AND p.owner_id=?)
                      AND EXISTS (SELECT 1 FROM memberships m
                                  WHERE m.project_id=applications.project_id AND m.user_id=applications.user_id)""",
                 (application_id, user["id"])),
            ])
            if results[1].meta.changes:
                return jsonify({"message": "已接受申请，队伍名额已更新。"})
        row = connection.execute("""
            SELECT a.status,p.owner_id,p.capacity,
                   (SELECT COUNT(*) FROM memberships m WHERE m.project_id=a.project_id) AS member_count
            FROM applications a JOIN projects p ON p.id=a.project_id WHERE a.id=?
        """, (application_id,)).fetchone()
        if not row:
            return error("申请不存在。", 404)
        if row["owner_id"] != user["id"]:
            return error("只有项目发起人可以处理申请。", 403)
        if row["status"] != "pending":
            return error("这份申请已经处理过。", 409)
        if decision == "accept" and row["member_count"] >= row["capacity"]:
            return error("项目已满员，无法接受更多申请。", 409)
        return error("申请状态已变化，请刷新后重试。", 409)
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute("""
            SELECT a.*,p.owner_id,p.capacity FROM applications a
            JOIN projects p ON p.id=a.project_id WHERE a.id=?
        """, (application_id,)).fetchone()
        if not row:
            connection.execute("ROLLBACK")
            return error("申请不存在。", 404)
        if row["owner_id"] != user["id"]:
            connection.execute("ROLLBACK")
            return error("只有项目发起人可以处理申请。", 403)
        if row["status"] != "pending":
            connection.execute("ROLLBACK")
            return error("这份申请已经处理过。", 409)
        if decision == "accept":
            count = connection.execute("SELECT COUNT(*) FROM memberships WHERE project_id=?",
                                       (row["project_id"],)).fetchone()[0]
            if count >= row["capacity"]:
                connection.execute("ROLLBACK")
                return error("项目已满员，无法接受更多申请。", 409)
            connection.execute("INSERT INTO memberships (project_id,user_id) VALUES (?,?)",
                               (row["project_id"], row["user_id"]))
        connection.execute("UPDATE applications SET status=? WHERE id=?",
                           ("accepted" if decision == "accept" else "rejected", application_id))
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    return jsonify({"message": "已接受申请，队伍名额已更新。" if decision == "accept" else "已拒绝申请。"})


def is_d1(connection):
    return not isinstance(connection, sqlite3.Connection)


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host=os.environ.get("APP_HOST", "127.0.0.1"),
            port=int(os.environ.get("APP_PORT", "5000")), threaded=True)
