import os
import sqlite3
import threading
import asyncio
import re
import unicodedata

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
# HÓNAP KEZELÉS
# =========================================================

def current_month():

    return datetime.now().strftime(
        "%Y-%m"
    )


def normalize_month(value):

    if not value:

        return current_month()

    try:

        datetime.strptime(
            value,
            "%Y-%m"
        )

        return value

    except ValueError:

        return current_month()


def get_selected_month():

    return normalize_month(
        request.args.get(
            "month",
            ""
        )
    )


def month_display(month_value):

    try:

        dt = datetime.strptime(
            month_value,
            "%Y-%m"
        )

        months = [
            "január",
            "február",
            "március",
            "április",
            "május",
            "június",
            "július",
            "augusztus",
            "szeptember",
            "október",
            "november",
            "december"
        ]

        return (
            f"{dt.year}. "
            f"{months[dt.month - 1]}"
        )

    except Exception:

        return month_value


# =========================================================
# ADATBÁZIS
# =========================================================

DB_PATH = os.environ.get(
    "DATABASE_PATH",
    "/tmp/nevsor.db"
)


def get_connection():

    conn = sqlite3.connect(
        DB_PATH
    )

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

    conn = g.pop(
        "db",
        None
    )

    if conn:

        conn.close()


# =========================================================
# ADATBÁZIS LÉTREHOZÁS / FRISSÍTÉS
# =========================================================

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

    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL,
        payment_month TEXT NOT NULL,
        payment_status INTEGER NOT NULL DEFAULT 0,
        payment_date TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,

        UNIQUE(member_id, payment_month),

        FOREIGN KEY(member_id)
            REFERENCES members(id)
            ON DELETE CASCADE
    );
    """)


    columns = conn.execute(
        "PRAGMA table_info(members)"
    ).fetchall()


    column_names = [

        column["name"]

        for column in columns

    ]


    if "payment_status" not in column_names:

        conn.execute("""
            ALTER TABLE members
            ADD COLUMN payment_status
            INTEGER NOT NULL DEFAULT 0
        """)


    if "payment_date" not in column_names:

        conn.execute("""
            ALTER TABLE members
            ADD COLUMN payment_date TEXT
        """)


    old_members = conn.execute("""
        SELECT
            id,
            payment_status,
            payment_date,
            created_at

        FROM members

        WHERE
            payment_status != 0
            OR payment_date IS NOT NULL
    """).fetchall()


    for member in old_members:

        if member["payment_date"]:

            try:

                payment_month = datetime.strptime(
                    member["payment_date"],
                    "%Y-%m-%d"
                ).strftime(
                    "%Y-%m"
                )

            except ValueError:

                payment_month = current_month()

        else:

            payment_month = current_month()


        existing = conn.execute("""
            SELECT id

            FROM payments

            WHERE
                member_id = ?
                AND payment_month = ?
        """, (
            member["id"],
            payment_month
        )).fetchone()


        if not existing:

            now = datetime.now().isoformat(
                timespec="seconds"
            )


            conn.execute("""
                INSERT INTO payments
                (
                    member_id,
                    payment_month,
                    payment_status,
                    payment_date,
                    created_at,
                    updated_at
                )

                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                member["id"],
                payment_month,
                int(member["payment_status"] or 0),
                member["payment_date"],
                member["created_at"] or now,
                now
            ))


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


    selected_month = get_selected_month()


    query = """
        SELECT

            m.id AS id,
            m.name AS name,
            m.character_id AS character_id,
            m.discord_user_id AS discord_user_id,
            m.discord_username AS discord_username,
            m.created_at AS created_at,

            COALESCE(
                pmt.payment_status,
                0
            ) AS payment_status,

            pmt.payment_date AS payment_date,

            COALESCE(
                SUM(p.points),
                0
            ) AS total_points

        FROM members m

        LEFT JOIN payments pmt

            ON pmt.member_id = m.id

            AND pmt.payment_month = ?

        LEFT JOIN penalty_log p

            ON p.member_id = m.id
    """


    params = [
        selected_month
    ]


    if q:

        query += """
            WHERE

                m.name LIKE ?

                OR m.character_id LIKE ?

                OR m.discord_username LIKE ?
        """


        like = f"%{q}%"


        params.extend([
            like,
            like,
            like
        ])


    query += """

        GROUP BY
            m.id,
            m.name,
            m.character_id,
            m.discord_user_id,
            m.discord_username,
            m.created_at,
            pmt.payment_status,
            pmt.payment_date

        ORDER BY
            m.name COLLATE NOCASE
    """


    members = db().execute(
        query,
        params
    ).fetchall()


    return render_template(
        "index.html",
        members=members,
        q=q,
        selected_month=selected_month,
        selected_month_display=month_display(
            selected_month
        ),
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


    payment_month = normalize_month(
        request.form.get(
            "month",
            ""
        )
    )


    if not name or not character_id:

        return redirect(
            url_for(
                "index",
                month=payment_month
            )
        )


    try:

        status = int(
            payment_status
        )

    except (
        ValueError,
        TypeError
    ):

        status = 0


    if status not in (
        0,
        1,
        2
    ):

        status = 0


    if status == 2:

        payment_date = ""


    now = datetime.now().isoformat(
        timespec="seconds"
    )


    try:

        conn = db()


        cursor = conn.execute("""
            INSERT INTO members
            (
                name,
                character_id,
                created_at
            )

            VALUES (?, ?, ?)
        """, (
            name,
            character_id,
            now
        ))


        member_id = cursor.lastrowid


        conn.execute("""
            INSERT INTO payments
            (
                member_id,
                payment_month,
                payment_status,
                payment_date,
                created_at,
                updated_at
            )

            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            member_id,
            payment_month,
            status,
            payment_date or None,
            now,
            now
        ))


        conn.commit()


    except sqlite3.IntegrityError:

        db().rollback()


    return redirect(
        url_for(
            "index",
            month=payment_month
        )
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


    payment_month = normalize_month(
        request.form.get(
            "month",
            ""
        )
    )


    if not name or not character_id:

        return redirect(
            url_for(
                "index",
                month=payment_month
            )
        )


    try:

        status = int(
            payment_status
        )

    except (
        ValueError,
        TypeError
    ):

        status = 0


    if status not in (
        0,
        1,
        2
    ):

        status = 0


    if status == 2:

        payment_date = ""


    now = datetime.now().isoformat(
        timespec="seconds"
    )


    try:

        conn = db()


        member_exists = conn.execute("""
            SELECT id
            FROM members
            WHERE id = ?
        """, (
            member_id,
        )).fetchone()


        if not member_exists:

            abort(404)


        conn.execute("""
            UPDATE members

            SET
                name = ?,
                character_id = ?

            WHERE id = ?
        """, (
            name,
            character_id,
            member_id
        ))


        existing = conn.execute("""
            SELECT id

            FROM payments

            WHERE
                member_id = ?

                AND payment_month = ?
        """, (
            member_id,
            payment_month
        )).fetchone()


        if existing:

            conn.execute("""
                UPDATE payments

                SET
                    payment_status = ?,
                    payment_date = ?,
                    updated_at = ?

                WHERE
                    member_id = ?

                    AND payment_month = ?
            """, (
                status,
                payment_date or None,
                now,
                member_id,
                payment_month
            ))

        else:

            conn.execute("""
                INSERT INTO payments
                (
                    member_id,
                    payment_month,
                    payment_status,
                    payment_date,
                    created_at,
                    updated_at
                )

                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                member_id,
                payment_month,
                status,
                payment_date or None,
                now,
                now
            ))


        conn.commit()


    except sqlite3.IntegrityError:

        db().rollback()


    return redirect(
        url_for(
            "index",
            month=payment_month
        )
    )


# =========================================================
# TAG ADATAI
# =========================================================

@app.route(
    "/member/<int:member_id>"
)
def member_detail(member_id):

    selected_month = normalize_month(
        request.args.get(
            "month",
            ""
        )
    )


    conn = db()


    member = conn.execute("""
        SELECT

            m.id AS id,
            m.name AS name,
            m.character_id AS character_id,
            m.discord_user_id AS discord_user_id,
            m.discord_username AS discord_username,

            COALESCE(
                pmt.payment_status,
                0
            ) AS payment_status,

            pmt.payment_date AS payment_date,

            COALESCE(
                SUM(p.points),
                0
            ) AS total_points

        FROM members m

        LEFT JOIN payments pmt

            ON pmt.member_id = m.id

            AND pmt.payment_month = ?

        LEFT JOIN penalty_log p

            ON p.member_id = m.id

        WHERE m.id = ?

        GROUP BY
            m.id,
            m.name,
            m.character_id,
            m.discord_user_id,
            m.discord_username,
            pmt.payment_status,
            pmt.payment_date
    """, (
        selected_month,
        member_id
    )).fetchone()


    if not member:

        abort(404)


    logs = conn.execute("""
        SELECT *

        FROM penalty_log

        WHERE member_id = ?

        ORDER BY id DESC
    """, (
        member_id,
    )).fetchall()


    return jsonify({

        "id": member["id"],

        "name": member["name"],

        "character_id": member["character_id"],

        "discord_user_id":
            member["discord_user_id"],

        "discord_username":
            member["discord_username"],

        "payment_status":
            int(
                member["payment_status"]
                or 0
            ),

        "payment_date":
            member["payment_date"],

        "payment_month":
            selected_month,

        "total_points":
            int(
                member["total_points"]
                or 0
            ),

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


    month = normalize_month(
        request.form.get(
            "month",
            ""
        )
    )


    try:

        points = int(
            points
        )

    except ValueError:

        points = 0


    if points > 0 and reason:

        db().execute("""
            INSERT INTO penalty_log
            (
                member_id,
                points,
                reason,
                created_at
            )

            VALUES (?, ?, ?, ?)
        """, (
            member_id,
            points,
            reason,
            datetime.now().isoformat(
                timespec="seconds"
            )
        ))

        db().commit()


    return redirect(
        url_for(
            "index",
            month=month
        )
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


    month = normalize_month(
        request.form.get(
            "month",
            ""
        )
    )


    conn = db()


    penalty = conn.execute("""
        SELECT member_id

        FROM penalty_log

        WHERE id = ?
    """, (
        penalty_id,
    )).fetchone()


    if not penalty:

        abort(404)


    conn.execute("""
        DELETE FROM penalty_log

        WHERE id = ?
    """, (
        penalty_id,
    ))


    conn.commit()


    return redirect(
        url_for(
            "index",
            month=month
        )
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


    month = normalize_month(
        request.form.get(
            "month",
            ""
        )
    )


    try:

        db().execute("""
            UPDATE members

            SET
                discord_user_id = ?,
                discord_username = ?

            WHERE id = ?
        """, (
            discord_user_id or None,
            discord_username or None,
            member_id
        ))

        db().commit()


    except sqlite3.IntegrityError:

        db().rollback()


    return redirect(
        url_for(
            "index",
            month=month
        )
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


    month = normalize_month(
        request.form.get(
            "month",
            ""
        )
    )


    db().execute("""
        DELETE FROM members

        WHERE id = ?
    """, (
        member_id,
    ))


    db().commit()


    return redirect(
        url_for(
            "index",
            month=month
        )
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


discord_loop = None
discord_started = False


intents = discord.Intents.default()

intents.message_content = True
intents.members = True


bot = commands.Bot(
    command_prefix="/",
    intents=intents
)


@bot.event
async def on_ready():

    global discord_loop

    discord_loop = asyncio.get_running_loop()

    print(
        f"Discord bot elindult: {bot.user}"
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


    member = conn.execute("""
        SELECT
            id,
            name,
            character_id

        FROM members

        WHERE character_id = ?
    """, (
        str(character_id),
    )).fetchone()


    if not member:

        conn.close()

        await ctx.send(
            f"❌ Nem található karakter "
            f"ezzel az ID-val: `{character_id}`"
        )

        return


    existing = conn.execute("""
        SELECT
            name,
            character_id

        FROM members

        WHERE discord_user_id = ?
    """, (
        str(ctx.author.id),
    )).fetchone()


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

        conn.execute("""
            UPDATE members

            SET
                discord_user_id = ?,
                discord_username = ?

            WHERE id = ?
        """, (
            str(ctx.author.id),
            ctx.author.display_name,
            member["id"]
        ))


        conn.commit()


        await ctx.send(
            "✅ **Sikeres összekapcsolás!**\n\n"
            f"👤 Karakter: **{member['name']}**\n"
            f"🆔 Karakter ID: `{member['character_id']}`\n"
            f"💬 Discord: **{ctx.author.display_name}**"
        )


    except sqlite3.IntegrityError:

        await ctx.send(
            "❌ Ez a Discord fiók vagy karakter "
            "már hozzá van rendelve valakihez."
        )


    finally:

        conn.close()


# =========================================================
# DISCORD NÉV NORMALIZÁLÁS
# =========================================================

def normalize_name(value):

    if not value:

        return ""


    value = str(value)
    value = value.strip()
    value = value.lstrip("@")
    value = value.casefold()

    value = unicodedata.normalize(
        "NFKD",
        value
    )

    value = "".join(
        char
        for char in value
        if not unicodedata.combining(char)
    )

    value = re.sub(
        r"[^a-z0-9]+",
        "",
        value
    )

    return value


# =========================================================
# DISCORD NÉV EGYEZÉS
# =========================================================

def names_match(
    db_name,
    discord_member
):

    normalized_db_name = normalize_name(
        db_name
    )


    if not normalized_db_name:

        return False


    possible_names = [

        getattr(
            discord_member,
            "name",
            None
        ),

        getattr(
            discord_member,
            "display_name",
            None
        ),

        getattr(
            discord_member,
            "global_name",
            None
        ),

        str(
            discord_member
        )

    ]


    for discord_name in possible_names:

        normalized_discord_name = normalize_name(
            discord_name
        )


        if not normalized_discord_name:

            continue


        if (
            normalized_discord_name
            == normalized_db_name
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
            f"Discord member chunk hiba: {repr(e)}"
        )


    conn = get_connection()


    try:

        members_db = conn.execute("""
            SELECT
                id,
                name,
                discord_user_id,
                discord_username

            FROM members
        """).fetchall()


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


            if (
                not found_member
                and db_member["discord_username"]
            ):

                saved_discord_name = normalize_name(
                    db_member[
                        "discord_username"
                    ]
                )


                for discord_member in guild.members:

                    if discord_member.bot:

                        continue


                    possible_names = [

                        discord_member.name,
                        discord_member.display_name,
                        discord_member.global_name,
                        str(discord_member)

                    ]


                    for possible_name in possible_names:

                        if (
                            normalize_name(
                                possible_name
                            )
                            == saved_discord_name
                        ):

                            found_member = discord_member

                            break


                    if found_member:

                        break


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


                conn.execute("""
                    UPDATE members

                    SET
                        discord_user_id = ?,
                        discord_username = ?

                    WHERE id = ?
                """, (
                    str(found_member.id),
                    found_member.display_name,
                    db_member["id"]
                ))


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
                len([
                    m
                    for m in guild.members
                    if not m.bot
                ]),

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


    finally:

        conn.close()


# =========================================================
# API - DISCORD ÖSSZEVETÉS
# =========================================================

@app.route(
    "/discord/sync",
    methods=["POST"]
)
def discord_sync():

    global discord_loop


    if not require_login():

        return jsonify({

            "success": False,

            "error":
                "Bejelentkezés szükséges."

        }), 401


    if not DISCORD_TOKEN:

        return jsonify({

            "success": False,

            "error":
                "DISCORD_TOKEN nincs beállítva."

        }), 503


    if not discord_started:

        return jsonify({

            "success": False,

            "error":
                "A Discord bot még nem indult el."

        }), 503


    if not bot.is_ready():

        return jsonify({

            "success": False,

            "error":
                "A Discord bot még nincs csatlakozva."

        }), 503


    if discord_loop is None:

        return jsonify({

            "success": False,

            "error":
                "A Discord bot eseményhurka még nem indult el."

        }), 503


    try:

        future = asyncio.run_coroutine_threadsafe(
            sync_discord_members(),
            discord_loop
        )


        result = future.result(
            timeout=30
        )


        return jsonify(
            result
        )


    except Exception as e:

        print(
            f"Discord sync hiba: {repr(e)}"
        )


        return jsonify({

            "success": False,

            "error":
                f"Discord sync hiba: {repr(e)}"

        }), 500


# =========================================================
# API - DISCORDON VAN, DE NINCS A NÉVSORBAN
# =========================================================

@app.route(
    "/discord/unmatched"
)
def discord_unmatched():

    if not require_login():

        return jsonify({
            "members": []
        })


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


    try:

        db_members = conn.execute("""
            SELECT
                name,
                discord_user_id,
                discord_username

            FROM members
        """).fetchall()

    finally:

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

                continue

            except (
                ValueError,
                TypeError
            ):

                pass


        if db_member["discord_username"]:

            saved_name = normalize_name(
                db_member[
                    "discord_username"
                ]
            )


            for discord_member in guild.members:

                if discord_member.bot:

                    continue


                possible_names = [

                    discord_member.name,
                    discord_member.display_name,
                    discord_member.global_name,
                    str(discord_member)

                ]


                if any(

                    normalize_name(x)
                    == saved_name

                    for x in possible_names

                    if x

                ):

                    used_ids.add(
                        discord_member.id
                    )

                    break


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

    global discord_loop


    if not DISCORD_TOKEN:

        print(
            "❌ DISCORD_TOKEN nincs beállítva!"
        )

        return


    async def start_bot():

        global discord_loop


        discord_loop = asyncio.get_running_loop()


        print(
            "🚀 Discord bot csatlakoztatása..."
        )


        await bot.start(
            DISCORD_TOKEN
        )


    try:

        asyncio.run(
            start_bot()
        )

    except Exception as e:

        print(
            f"❌ Discord bot hiba: {repr(e)}"
        )


def start_discord_bot():

    global discord_started


    if discord_started:

        return


    if not DISCORD_TOKEN:

        print(
            "❌ DISCORD_TOKEN nincs beállítva!"
        )

        return


    discord_started = True


    print(
        "🚀 Discord bot indítása..."
    )


    discord_thread = threading.Thread(
        target=run_discord_bot,
        daemon=True
    )


    discord_thread.start()


# =========================================================
# ALKALMAZÁS ELŐKÉSZÍTÉSE
# =========================================================

init_db()

start_discord_bot()


# =========================================================
# PROGRAM INDÍTÁSA
# =========================================================

if __name__ == "__main__":

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
