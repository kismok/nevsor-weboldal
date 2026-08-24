import os
import sqlite3
import threading
import asyncio
from datetime import datetime

import discord
from discord.ext import commands

from flask import (
    Flask,
    g,
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    abort,
    session
)


# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)


# =========================================================
# SESSION TITKOSÍTÓ KULCS
# =========================================================

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "csereld-le-egy-hosszu-titkos-kulcsra"
)


# =========================================================
# BEJELENTKEZÉSI ADATOK
# =========================================================

ADMIN_USERNAME = os.environ.get(
    "ADMIN_USERNAME",
    "admin"
)

ADMIN_PASSWORD = os.environ.get(
    "ADMIN_PASSWORD",
    "admin123"
)


def is_logged_in():

    return session.get("logged_in") is True


def require_login():

    return is_logged_in()


# =========================================================
# ADATBÁZIS
# =========================================================

DB_PATH = os.environ.get(
    "DATABASE_PATH",
    "/tmp/nevsor.db"
)


def get_connection():

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    return conn


def db():

    if "db" not in g:

        g.db = get_connection()

    return g.db


@app.teardown_appcontext
def close_db(_error=None):

    conn = g.pop("db", None)

    if conn:

        conn.close()


def init_db():

    conn = get_connection()

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        character_id TEXT NOT NULL UNIQUE,
        discord_user_id TEXT UNIQUE,
        discord_username TEXT,

        payment_status INTEGER NOT NULL DEFAULT 0,
        payment_date TEXT,

        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS penalty_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL,
        points INTEGER NOT NULL,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL,

        FOREIGN KEY(member_id)
            REFERENCES members(id)
            ON DELETE CASCADE
    );
    """)


    # =====================================================
    # RÉGI ADATBÁZIS FRISSÍTÉSE
    # =====================================================

    columns = conn.execute(
        "PRAGMA table_info(members)"
    ).fetchall()

    column_names = [
        column["name"]
        for column in columns
    ]


    if "payment_status" not in column_names:

        conn.execute(
            """
            ALTER TABLE members
            ADD COLUMN payment_status INTEGER NOT NULL DEFAULT 0
            """
        )


    if "payment_date" not in column_names:

        conn.execute(
            """
            ALTER TABLE members
            ADD COLUMN payment_date TEXT
            """
        )


    conn.commit()

    conn.close()


# =========================================================
# BEJELENTKEZÉS
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        if (
            username == ADMIN_USERNAME
            and password == ADMIN_PASSWORD
        ):

            session["logged_in"] = True

            return redirect(
                url_for("index")
            )

        return render_template(
            "login.html",
            error="Hibás felhasználónév vagy jelszó."
        )

    return render_template(
        "login.html",
        error=None
    )


# =========================================================
# KIJELENTKEZÉS
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("index")
    )


# =========================================================
# WEBOLDAL
# =========================================================

@app.route("/")
def index():

    q = request.args.get(
        "q",
        ""
    ).strip()

    query = """
        SELECT
            m.*,
            COALESCE(SUM(p.points), 0) AS total_points

        FROM members m

        LEFT JOIN penalty_log p
            ON p.member_id = m.id
    """

    params = []

    if q:

        query += """
            WHERE
                m.name LIKE ?
                OR m.character_id LIKE ?
                OR m.discord_username LIKE ?
        """

        like = f"%{q}%"

        params = [
            like,
            like,
            like
        ]

    query += """
        GROUP BY m.id
        ORDER BY m.name COLLATE NOCASE
    """

    members = db().execute(
        query,
        params
    ).fetchall()

    return render_template(
        "index.html",
        members=members,
        q=q,
        logged_in=is_logged_in()
    )


# =========================================================
# ÚJ TAG HOZZÁADÁSA
# =========================================================

@app.route(
    "/member/add",
    methods=["POST"]
)
def add_member():

    if not require_login():

        return redirect(
            url_for("login")
        )

    name = request.form.get(
        "name",
        ""
    ).strip()

    character_id = request.form.get(
        "character_id",
        ""
    ).strip()

    payment_status = request.form.get(
        "payment_status",
        "0"
    )

    payment_date = request.form.get(
        "payment_date",
        ""
    ).strip()


    if not name or not character_id:

        return redirect(
            url_for("index")
        )


    try:

        db().execute(
            """
            INSERT INTO members
            (
                name,
                character_id,
                payment_status,
                payment_date,
                created_at
            )

            VALUES (?, ?, ?, ?, ?)
            """,
            (
                name,
                character_id,
                int(payment_status),
                payment_date or None,
                datetime.now().isoformat(
                    timespec="seconds"
                )
            )
        )

        db().commit()

    except sqlite3.IntegrityError:

        pass

    return redirect(
        url_for("index")
    )


# =========================================================
# TAG SZERKESZTÉSE
# =========================================================

@app.route(
    "/member/<int:member_id>/edit",
    methods=["POST"]
)
def edit_member(member_id):

    if not require_login():

        return redirect(
            url_for("login")
        )

    name = request.form.get(
        "name",
        ""
    ).strip()

    character_id = request.form.get(
        "character_id",
        ""
    ).strip()

    payment_status = request.form.get(
        "payment_status",
        "0"
    )

    payment_date = request.form.get(
        "payment_date",
        ""
    ).strip()


    if not name or not character_id:

        return redirect(
            url_for("index")
        )


    try:

        db().execute(
            """
            UPDATE members

            SET
                name = ?,
                character_id = ?,
                payment_status = ?,
                payment_date = ?

            WHERE id = ?
            """,
            (
                name,
                character_id,
                int(payment_status),
                payment_date or None,
                member_id
            )
        )

        db().commit()

    except sqlite3.IntegrityError:

        pass

    return redirect(
        url_for("index")
    )


# =========================================================
# TAG ADATAI
# =========================================================

@app.route(
    "/member/<int:member_id>"
)
def member_detail(member_id):

    conn = db()

    member = conn.execute(
        """
        SELECT
            m.*,
            COALESCE(SUM(p.points), 0) AS total_points

        FROM members m

        LEFT JOIN penalty_log p
            ON p.member_id = m.id

        WHERE m.id = ?

        GROUP BY m.id
        """,
        (member_id,)
    ).fetchone()

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

        "id":
            member["id"],

        "name":
            member["name"],

        "character_id":
            member["character_id"],

        "discord_user_id":
            member["discord_user_id"],

        "discord_username":
            member["discord_username"],

        "payment_status":
            member["payment_status"],

        "payment_date":
            member["payment_date"],

        "total_points":
            member["total_points"],

        "logged_in":
            is_logged_in(),

        "logs":
            [
                dict(x)
                for x in logs
            ]

    })


# =========================================================
# HIBAPONT HOZZÁADÁSA
# =========================================================

@app.route(
    "/member/<int:member_id>/penalty",
    methods=["POST"]
)
def add_penalty(member_id):

    if not require_login():

        return redirect(
            url_for("login")
        )

    points = request.form.get(
        "points",
        "0"
    ).strip()

    reason = request.form.get(
        "reason",
        ""
    ).strip()

    try:

        points = int(points)

    except ValueError:

        points = 0

    if points > 0 and reason:

        db().execute(
            """
            INSERT INTO penalty_log
            (
                member_id,
                points,
                reason,
                created_at
            )

            VALUES (?, ?, ?, ?)
            """,
            (
                member_id,
                points,
                reason,
                datetime.now().isoformat(
                    timespec="seconds"
                )
            )
        )

        db().commit()

    return redirect(
        url_for("index")
    )


# =========================================================
# HIBAPONT TÖRLÉSE
# =========================================================

@app.route(
    "/penalty/<int:penalty_id>/delete",
    methods=["POST"]
)
def delete_penalty(penalty_id):

    if not require_login():

        return redirect(
            url_for("login")
        )

    conn = db()

    penalty = conn.execute(
        """
        SELECT member_id

        FROM penalty_log

        WHERE id = ?
        """,
        (penalty_id,)
    ).fetchone()

    if not penalty:

        abort(404)

    conn.execute(
        """
        DELETE FROM penalty_log

        WHERE id = ?
        """,
        (penalty_id,)
    )

    conn.commit()

    return redirect(
        url_for("index")
    )


# =========================================================
# DISCORD KÉZI BEÁLLÍTÁS
# =========================================================

@app.route(
    "/member/<int:member_id>/discord",
    methods=["POST"]
)
def set_discord(member_id):

    if not require_login():

        return redirect(
            url_for("login")
        )

    discord_user_id = request.form.get(
        "discord_user_id",
        ""
    ).strip()

    discord_username = request.form.get(
        "discord_username",
        ""
    ).strip()

    try:

        db().execute(
            """
            UPDATE members

            SET
                discord_user_id = ?,
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

    except sqlite3.IntegrityError:

        pass

    return redirect(
        url_for("index")
    )


# =========================================================
# TAG TÖRLÉSE
# =========================================================

@app.route(
    "/member/<int:member_id>/delete",
    methods=["POST"]
)
def delete_member(member_id):

    if not require_login():

        return redirect(
            url_for("login")
        )

    db().execute(
        """
        DELETE FROM members

        WHERE id = ?
        """,
        (member_id,)
    )

    db().commit()

    return redirect(
        url_for("index")
    )


# =========================================================
# DISCORD BOT
# =========================================================

DISCORD_TOKEN = os.environ.get(
    "DISCORD_TOKEN"
)

DISCORD_GUILD_ID = os.environ.get(
    "DISCORD_GUILD_ID"
)


intents = discord.Intents.default()

intents.message_content = True
intents.members = True


bot = commands.Bot(
    command_prefix="/",
    intents=intents
)


@bot.event
async def on_ready():

    print(
        f"Discord bot elindult: "
        f"{bot.user}"
    )


# =========================================================
# /LINK KARAKTER_ID
# =========================================================

@bot.command(
    name="link"
)
async def link_character(
    ctx,
    character_id=None
):

    if not character_id:

        await ctx.send(
            "❌ Használat: `/link KARAKTER_ID`"
        )

        return

    conn = get_connection()

    member = conn.execute(
        """
        SELECT
            id,
            name,
            character_id

        FROM members

        WHERE character_id = ?
        """,
        (str(character_id),)
    ).fetchone()

    if not member:

        conn.close()

        await ctx.send(
            f"❌ Nem található karakter "
            f"ezzel az ID-val: `{character_id}`"
        )

        return

    existing = conn.execute(
        """
        SELECT
            name,
            character_id

        FROM members

        WHERE discord_user_id = ?
        """,
        (str(ctx.author.id),)
    ).fetchone()

    if existing:

        conn.close()

        await ctx.send(
            "⚠️ Ez a Discord fiók már össze van kapcsolva "
            f"a következő karakterrel: "
            f"**{existing['name']}** "
            f"(ID: `{existing['character_id']}`)"
        )

        return

    try:

        conn.execute(
            """
            UPDATE members

            SET
                discord_user_id = ?,
                discord_username = ?

            WHERE id = ?
            """,
            (
                str(ctx.author.id),
                str(ctx.author),
                member["id"]
            )
        )

        conn.commit()

        await ctx.send(
            "✅ **Sikeres összekapcsolás!**\n\n"
            f"👤 Karakter: **{member['name']}**\n"
            f"🆔 Karakter ID: `{member['character_id']}`\n"
            f"💬 Discord: **{ctx.author}**"
        )

    except sqlite3.IntegrityError:

        await ctx.send(
            "❌ Ez a Discord fiók vagy karakter "
            "már hozzá van rendelve valakihez."
        )

    finally:

        conn.close()


# =========================================================
# DISCORD NÉV EGYEZÉS
# =========================================================

def names_match(db_name, discord_member):

    if not db_name:

        return False

    db_name = db_name.strip().lower()

    possible_names = [

        discord_member.name,

        discord_member.display_name,

        discord_member.global_name,

        str(discord_member)

    ]

    for discord_name in possible_names:

        if not discord_name:

            continue

        if (
            discord_name
            .strip()
            .lower()
            == db_name
        ):

            return True

    return False


# =========================================================
# DISCORD SZERVER ÖSSZEVETÉS
# =========================================================

async def sync_discord_members():

    if not DISCORD_GUILD_ID:

        return {
            "success": False,
            "error": "DISCORD_GUILD_ID nincs beállítva."
        }

    try:

        guild_id = int(
            DISCORD_GUILD_ID
        )

    except ValueError:

        return {
            "success": False,
            "error": "Hibás DISCORD_GUILD_ID."
        }

    guild = bot.get_guild(
        guild_id
    )

    if not guild:

        return {
            "success": False,
            "error": "A Discord szerver nem található."
        }

    try:

        await guild.chunk()

    except Exception as e:

        print(
            f"Discord member chunk hiba: {e}"
        )

    conn = get_connection()

    members_db = conn.execute(
        """
        SELECT
            id,
            name,
            discord_user_id,
            discord_username

        FROM members
        """
    ).fetchall()

    linked = []

    not_found = []

    used_discord_ids = set()

    for db_member in members_db:

        found_member = None

        if db_member["discord_user_id"]:

            try:

                found_member = guild.get_member(
                    int(
                        db_member[
                            "discord_user_id"
                        ]
                    )
                )

            except (
                ValueError,
                TypeError
            ):

                found_member = None

        if not found_member:

            for discord_member in guild.members:

                if discord_member.bot:

                    continue

                if names_match(
                    db_member["name"],
                    discord_member
                ):

                    found_member = discord_member

                    break

        if found_member:

            used_discord_ids.add(
                found_member.id
            )

            conn.execute(
                """
                UPDATE members

                SET
                    discord_user_id = ?,
                    discord_username = ?

                WHERE id = ?
                """,
                (
                    str(found_member.id),

                    found_member.display_name,

                    db_member["id"]
                )
            )

            linked.append({

                "member_id":
                    db_member["id"],

                "name":
                    db_member["name"],

                "discord":
                    found_member.display_name

            })

        else:

            not_found.append({

                "member_id":
                    db_member["id"],

                "name":
                    db_member["name"]

            })

    conn.commit()

    conn.close()

    discord_only = []

    for discord_member in guild.members:

        if discord_member.bot:

            continue

        if discord_member.id not in used_discord_ids:

            discord_only.append({

                "id":
                    str(discord_member.id),

                "username":
                    discord_member.name,

                "display_name":
                    discord_member.display_name

            })

    return {

        "success": True,

        "total":
            len(
                [
                    m
                    for m in guild.members
                    if not m.bot
                ]
            ),

        "matched":
            len(linked),

        "unmatched":
            len(discord_only),

        "linked":
            linked,

        "not_found":
            not_found,

        "discord_only":
            discord_only

    }


# =========================================================
# API - DISCORD ÖSSZEVETÉS
# =========================================================

@app.route(
    "/discord/sync",
    methods=["POST"]
)
def discord_sync():

    if not require_login():

        return jsonify({
            "success": False,
            "error": "Bejelentkezés szükséges."
        }), 401

    if not bot.is_ready():

        return jsonify({

            "success": False,

            "error":
                "A Discord bot még nincs csatlakozva."

        }), 503

    future = asyncio.run_coroutine_threadsafe(
        sync_discord_members(),
        bot.loop
    )

    try:

        result = future.result(
            timeout=30
        )

        return jsonify(
            result
        )

    except Exception as e:

        return jsonify({

            "success": False,

            "error": str(e)

        }), 500


# =========================================================
# API - DISCORDON VAN, DE NINCS A NÉVSORBAN
# =========================================================

@app.route(
    "/discord/unmatched"
)
def discord_unmatched():

    if not bot.is_ready():

        return jsonify({
            "members": []
        })

    if not DISCORD_GUILD_ID:

        return jsonify({
            "members": []
        })

    try:

        guild_id = int(
            DISCORD_GUILD_ID
        )

    except ValueError:

        return jsonify({
            "members": []
        })

    guild = bot.get_guild(
        guild_id
    )

    if not guild:

        return jsonify({
            "members": []
        })

    conn = get_connection()

    db_members = conn.execute(
        """
        SELECT
            name,
            discord_user_id
        FROM members
        """
    ).fetchall()

    conn.close()

    used_ids = set()

    for db_member in db_members:

        if db_member["discord_user_id"]:

            try:

                used_ids.add(
                    int(
                        db_member[
                            "discord_user_id"
                        ]
                    )
                )

            except (
                ValueError,
                TypeError
            ):

                pass

        else:

            for discord_member in guild.members:

                if discord_member.bot:

                    continue

                if names_match(
                    db_member["name"],
                    discord_member
                ):

                    used_ids.add(
                        discord_member.id
                    )

                    break

    members = []

    for discord_member in guild.members:

        if discord_member.bot:

            continue

        if discord_member.id not in used_ids:

            members.append({

                "id":
                    str(discord_member.id),

                "username":
                    discord_member.name,

                "display_name":
                    discord_member.display_name

            })

    return jsonify({

        "members":
            members

    })


# =========================================================
# DISCORD BOT INDÍTÁSA
# =========================================================

def run_discord_bot():

    if not DISCORD_TOKEN:

        print(
            "DISCORD_TOKEN nincs beállítva!"
        )

        return

    bot.run(
        DISCORD_TOKEN
    )


# =========================================================
# PROGRAM INDÍTÁSA
# =========================================================

if __name__ == "__main__":

    init_db()

    discord_thread = threading.Thread(
        target=run_discord_bot,
        daemon=True
    )

    discord_thread.start()

    port = int(
        os.environ.get(
            "PORT",
            "3000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
