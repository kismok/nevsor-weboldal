import os
import sqlite3
from datetime import datetime
from flask import Flask, g, render_template, request, redirect, url_for, jsonify, abort

app = Flask(__name__)

# Belmo környezetben az /app mappa írásvédett,
# ezért az SQLite adatbázist a /tmp mappában tároljuk.
DB_PATH = os.environ.get("DATABASE_PATH", "/tmp/nevsor.db")


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    conn = g.pop("db", None)

    if conn:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)

    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        character_id TEXT NOT NULL UNIQUE,
        discord_user_id TEXT,
        discord_username TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS penalty_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL,
        points INTEGER NOT NULL,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE CASCADE
    );
    """)

    conn.commit()
    conn.close()


@app.route("/")
def index():
    q = request.args.get("q", "").strip()

    query = """
        SELECT m.*,
               COALESCE(SUM(p.points), 0) AS total_points
        FROM members m
        LEFT JOIN penalty_log p ON p.member_id = m.id
    """

    params = []

    if q:
        query += """
            WHERE m.name LIKE ?
            OR m.character_id LIKE ?
            OR m.discord_username LIKE ?
        """

        like = f"%{q}%"
        params = [like, like, like]

    query += """
        GROUP BY m.id
        ORDER BY m.name COLLATE NOCASE
    """

    members = db().execute(query, params).fetchall()

    return render_template(
        "index.html",
        members=members,
        q=q
    )


@app.route("/member/add", methods=["POST"])
def add_member():
    name = request.form.get("name", "").strip()
    character_id = request.form.get("character_id", "").strip()

    if not name or not character_id:
        return redirect(url_for("index"))

    try:
        db().execute(
            """
            INSERT INTO members
            (name, character_id, created_at)
            VALUES (?, ?, ?)
            """,
            (
                name,
                character_id,
                datetime.now().isoformat(timespec="seconds")
            )
        )

        db().commit()

    except sqlite3.IntegrityError:
        pass

    return redirect(url_for("index"))


@app.route("/member/<int:member_id>")
def member_detail(member_id):
    conn = db()

    member = conn.execute("""
        SELECT m.*,
               COALESCE(SUM(p.points), 0) AS total_points
        FROM members m
        LEFT JOIN penalty_log p ON p.member_id = m.id
        WHERE m.id = ?
        GROUP BY m.id
    """, (member_id,)).fetchone()

    if not member:
        abort(404)

    logs = conn.execute(
        """
        SELECT *
        FROM penalty_log
        WHERE member_id = ?
        ORDER BY id DESC
        """,
        (member_id,)
    ).fetchall()

    return jsonify({
        "id": member["id"],
        "name": member["name"],
        "character_id": member["character_id"],
        "discord_user_id": member["discord_user_id"],
        "discord_username": member["discord_username"],
        "total_points": member["total_points"],
        "logs": [dict(x) for x in logs]
    })


@app.route("/member/<int:member_id>/penalty", methods=["POST"])
def add_penalty(member_id):
    points = request.form.get("points", "0").strip()
    reason = request.form.get("reason", "").strip()

    try:
        points = int(points)
    except ValueError:
        points = 0

    if points and reason:
        db().execute(
            """
            INSERT INTO penalty_log
            (member_id, points, reason, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                member_id,
                points,
                reason,
                datetime.now().isoformat(timespec="seconds")
            )
        )

        db().commit()

    return redirect(url_for("index"))


@app.route("/member/<int:member_id>/discord", methods=["POST"])
def set_discord(member_id):
    discord_user_id = request.form.get(
        "discord_user_id",
        ""
    ).strip()

    discord_username = request.form.get(
        "discord_username",
        ""
    ).strip()

    db().execute(
        """
        UPDATE members
        SET discord_user_id = ?,
            discord_username = ?
        WHERE id = ?
        """,
        (
            discord_user_id or None,
            discord_username or None,
            member_id
        )
    )

    db().commit()

    return redirect(url_for("index"))


@app.route("/member/<int:member_id>/delete", methods=["POST"])
def delete_member(member_id):
    db().execute(
        "DELETE FROM members WHERE id = ?",
        (member_id,)
    )

    db().commit()

    return redirect(url_for("index"))


if __name__ == "__main__":
    init_db()

    port = int(os.environ.get("PORT", "3000"))

    app.run(
        host="0.0.0.0",
        port=port
    )