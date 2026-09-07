import os
import secrets
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_conn():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    conn.autocommit = True
    return conn


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    link_token TEXT UNIQUE NOT NULL,
                    is_banned BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
            # برای دیتابیس‌هایی که از قبل ساخته شدن و ستون جدید رو ندارن
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT;")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS anon_identities (
                    owner_id BIGINT NOT NULL,
                    sender_id BIGINT NOT NULL,
                    anon_number INTEGER NOT NULL,
                    PRIMARY KEY (owner_id, sender_id)
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS blocks (
                    owner_id BIGINT NOT NULL,
                    sender_id BIGINT NOT NULL,
                    blocked_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (owner_id, sender_id)
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS support_tickets (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    message TEXT NOT NULL,
                    reply TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    owner_id BIGINT NOT NULL,
                    sender_id BIGINT NOT NULL,
                    direction TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    text_content TEXT,
                    file_id TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id SERIAL PRIMARY KEY,
                    owner_id BIGINT NOT NULL,
                    sender_id BIGINT NOT NULL,
                    message_text TEXT,
                    content_type TEXT,
                    file_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)


def get_or_create_user(user_id, username, first_name=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if row:
                # اگه یوزرنیم یا اسم عوض شده باشه، به‌روزش می‌کنیم
                if row["username"] != username or row.get("first_name") != first_name:
                    cur.execute(
                        "UPDATE users SET username = %s, first_name = %s WHERE id = %s RETURNING *",
                        (username, first_name, user_id),
                    )
                    return cur.fetchone()
                return row
            token = secrets.token_urlsafe(6)
            cur.execute(
                "INSERT INTO users (id, username, first_name, link_token) VALUES (%s, %s, %s, %s) RETURNING *",
                (user_id, username, first_name, token),
            )
            return cur.fetchone()


def get_user_by_token(token):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE link_token = %s", (token,))
            return cur.fetchone()


def get_user_by_id(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return cur.fetchone()


def get_anon_number(owner_id, sender_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT anon_number FROM anon_identities WHERE owner_id=%s AND sender_id=%s",
                (owner_id, sender_id),
            )
            row = cur.fetchone()
            if row:
                return row["anon_number"]
            cur.execute(
                "SELECT COALESCE(MAX(anon_number), 0) + 1 AS next FROM anon_identities WHERE owner_id=%s",
                (owner_id,),
            )
            next_num = cur.fetchone()["next"]
            cur.execute(
                "INSERT INTO anon_identities (owner_id, sender_id, anon_number) VALUES (%s, %s, %s)",
                (owner_id, sender_id, next_num),
            )
            return next_num


def is_blocked(owner_id, sender_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM blocks WHERE owner_id=%s AND sender_id=%s",
                (owner_id, sender_id),
            )
            return cur.fetchone() is not None


def block_user(owner_id, sender_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO blocks (owner_id, sender_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (owner_id, sender_id),
            )


def unblock_user(owner_id, sender_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM blocks WHERE owner_id=%s AND sender_id=%s",
                (owner_id, sender_id),
            )


def list_blocked(owner_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT b.sender_id, a.anon_number
                FROM blocks b
                JOIN anon_identities a
                  ON a.owner_id = b.owner_id AND a.sender_id = b.sender_id
                WHERE b.owner_id = %s
                ORDER BY a.anon_number
            """, (owner_id,))
            return cur.fetchall()


def log_message(owner_id, sender_id, direction, content_type, text_content=None, file_id=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO messages (owner_id, sender_id, direction, content_type, text_content, file_id)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (owner_id, sender_id, direction, content_type, text_content, file_id),
            )


def get_last_message(owner_id, sender_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM messages
                   WHERE owner_id = %s AND sender_id = %s AND direction = 'to_owner'
                   ORDER BY created_at DESC LIMIT 1""",
                (owner_id, sender_id),
            )
            return cur.fetchone()


def create_report(owner_id, sender_id, content_type, text_content, file_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO reports (owner_id, sender_id, content_type, message_text, file_id)
                   VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                (owner_id, sender_id, content_type, text_content, file_id),
            )
            return cur.fetchone()


def get_pending_reports():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM reports WHERE status = 'pending' ORDER BY created_at DESC")
            return cur.fetchall()


def resolve_report(report_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE reports SET status = 'resolved' WHERE id = %s", (report_id,))


def create_ticket(user_id, message):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO support_tickets (user_id, message) VALUES (%s, %s) RETURNING *",
                (user_id, message),
            )
            return cur.fetchone()


def get_ticket(ticket_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM support_tickets WHERE id = %s", (ticket_id,))
            return cur.fetchone()


def get_answered_tickets():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM support_tickets WHERE status = 'answered'")
            return cur.fetchall()


def mark_ticket_delivered(ticket_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE support_tickets SET status = 'delivered' WHERE id = %s", (ticket_id,))


def reply_ticket(ticket_id, reply_text):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE support_tickets SET reply = %s, status = 'answered' WHERE id = %s",
                (reply_text, ticket_id),
            )


def get_pending_tickets():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM support_tickets WHERE status = 'pending' ORDER BY created_at")
            return cur.fetchall()


def ban_user(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET is_banned = TRUE WHERE id = %s", (user_id,))


def unban_user(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET is_banned = FALSE WHERE id = %s", (user_id,))


def get_stats():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS c FROM users")
            users_count = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM messages")
            messages_count = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM blocks")
            blocks_count = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM support_tickets WHERE status = 'pending'")
            pending_tickets = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM reports WHERE status = 'pending'")
            pending_reports = cur.fetchone()["c"]
            return {
                "users": users_count,
                "messages": messages_count,
                "blocks": blocks_count,
                "pending_tickets": pending_tickets,
                "pending_reports": pending_reports,
            }


def list_users(offset=0, limit=10):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM users ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
            return cur.fetchall()


def search_user(query):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if query.isdigit():
                cur.execute("SELECT * FROM users WHERE id = %s", (int(query),))
            else:
                cur.execute("SELECT * FROM users WHERE username ILIKE %s", (f"%{query}%",))
            return cur.fetchall()


def get_user_messages(user_id, limit=20):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM messages WHERE owner_id = %s OR sender_id = %s
                   ORDER BY created_at DESC LIMIT %s""",
                (user_id, user_id, limit),
            )
            return cur.fetchall()
