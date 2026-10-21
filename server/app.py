#!/usr/bin/env python3
"""Kamla Dei — web platform backend (stdlib only).

Auth, subscriptions, access keys, brain-proxy chat with quotas, admin.
Run:  python server/app.py     ->  http://127.0.0.1:8080
Env (optional, set by owner — NEVER in chat):
  KAMLA_API_BASE / KAMLA_API_KEY / KAMLA_MODEL   -> real LLM brain
  KAMLA_ADMIN_EMAIL / KAMLA_ADMIN_PASSWORD       -> admin account
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(BASE, "web")
DATA = os.path.join(BASE, "data")
os.makedirs(DATA, exist_ok=True)
DB_PATH = os.path.join(DATA, "kamla.db")

# Optional kamla.env next to the app (owner's own keys — never shared):
#   KAMLA_API_KEY=...  /  KAMLA_MODEL=...  /  KAMLA_ADMIN_PASSWORD=...
_envf = os.path.join(BASE, "kamla.env")
if os.path.exists(_envf):
    for _line in open(_envf, encoding="utf-8"):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
PORT = int(os.environ.get("PORT", "8790"))  # 8080 llama.cpp-র সাথে ধাক্কা খায়

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("KAMLA_SERVER", "1")
from engine import tools as engine_tools  # noqa: E402
from engine.brain import RouterBrain  # noqa: E402
from engine.demo_brain import DemoBrain  # noqa: E402
from engine.loop import Agent  # noqa: E402
from engine.memory import Memory  # noqa: E402

PLANS = {
    "free":   {"name": "Free",   "price": 0,   "daily": 20,   "devices": 1},
    "pro":    {"name": "Pro",    "price": 300, "daily": 500,  "devices": 2},
    "family": {"name": "Family", "price": 800, "daily": 1000, "devices": 5},
}

# ---------- secret for token signing (kept on disk, never printed) ----
_secret_file = os.path.join(DATA, "secret.txt")
if os.path.exists(_secret_file):
    SECRET = open(_secret_file).read().strip()
else:
    SECRET = secrets.token_hex(32)
    with open(_secret_file, "w") as f:
        f.write(SECRET)


# ---------- database ----------------------------------------------------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, email TEXT UNIQUE, pw TEXT, salt TEXT,
        role TEXT DEFAULT 'user', created_at TEXT);
    CREATE TABLE IF NOT EXISTS subscriptions(
        user_id INTEGER PRIMARY KEY, plan TEXT DEFAULT 'free',
        expires_at TEXT);
    CREATE TABLE IF NOT EXISTS keys(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE, plan TEXT, days INTEGER,
        used_by INTEGER, used_at TEXT, created_at TEXT,
        revoked INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS usage(
        user_id INTEGER, day TEXT, count INTEGER DEFAULT 0,
        PRIMARY KEY(user_id, day));
    CREATE TABLE IF NOT EXISTS chats(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, title TEXT DEFAULT 'নতুন চ্যাট',
        created_at TEXT, hist TEXT DEFAULT '[]');
    CREATE TABLE IF NOT EXISTS chat_msgs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER, who TEXT, text TEXT, ts TEXT);
    """)
    c.commit()
    # seed admin
    email = os.environ.get("KAMLA_ADMIN_EMAIL", "admin@kamladei.app")
    pw = os.environ.get("KAMLA_ADMIN_PASSWORD", "admin123")
    row = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if not row:
        salt, hashed = hash_pw(pw)
        cur = c.execute(
            "INSERT INTO users(name,email,pw,salt,role,created_at) "
            "VALUES(?,?,?,?,?,?)",
            ("Admin", email, hashed, salt, "admin", now_iso()))
        c.execute("INSERT INTO subscriptions(user_id,plan,expires_at) "
                  "VALUES(?,?,?)", (cur.lastrowid, "family", None))
        c.commit()
        print("👑 Admin তৈরি: %s (password: %s)" % (email, pw))
        if pw == "admin123":
            print("   ⚠️ ডিফল্ট password! KAMLA_ADMIN_PASSWORD env দিয়ে বদলাও।")
    c.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today():
    return datetime.now().strftime("%Y-%m-%d")


# ---------- auth ---------------------------------------------------------
def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000)
    return salt, h.hex()


def make_token(user_id):
    exp = int(time.time()) + 7 * 24 * 3600
    payload = "%d.%d" % (user_id, exp)
    sig = hmac.new(SECRET.encode(), payload.encode(),
                   hashlib.sha256).hexdigest()
    return "%s.%s" % (payload, sig)


def parse_token(tok):
    try:
        uid, exp, sig = tok.split(".")
        payload = "%s.%s" % (uid, exp)
        want = hmac.new(SECRET.encode(), payload.encode(),
                        hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, want):
            return None
        if int(exp) < int(time.time()):
            return None
        return int(uid)
    except Exception:
        return None


def get_user(conn, uid):
    return conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def user_plan(conn, uid):
    """(plan_key, expires_at or None, active_bool)"""
    row = conn.execute("SELECT * FROM subscriptions WHERE user_id=?",
                       (uid,)).fetchone()
    if not row:
        return "free", None, True
    plan, exp = row["plan"], row["expires_at"]
    if plan == "free":
        return "free", None, True
    if exp and datetime.fromisoformat(exp) > datetime.now(timezone.utc):
        return plan, exp, True
    return "free", exp, False  # expired -> falls back to free


def usage_today(conn, uid):
    row = conn.execute("SELECT count FROM usage WHERE user_id=? AND day=?",
                       (uid, today())).fetchone()
    return row["count"] if row else 0


def bump_usage(conn, uid):
    conn.execute("INSERT INTO usage(user_id,day,count) VALUES(?,?,1) "
                 "ON CONFLICT(user_id,day) DO UPDATE SET count=count+1",
                 (uid, today()))
    conn.commit()


# ---------- agent engine glue (per-user workspaces + sessions) ---------
def brain_mode():
    return "live" if RouterBrain().configured() else "demo"


def user_dir(uid):
    d = os.path.join(DATA, "users", str(uid))
    os.makedirs(os.path.join(d, "workspace"), exist_ok=True)
    return d


def insert_msg(chat_id, who, text):
    conn = db()
    conn.execute("INSERT INTO chat_msgs(chat_id,who,text,ts) VALUES(?,?,?,?)",
                 (chat_id, who, str(text), now_iso()))
    conn.commit()
    conn.close()


SESSIONS = {}


def get_sess(chat_id):
    return SESSIONS.setdefault(chat_id, {
        "busy": False, "approval": None,
        "event": threading.Event(), "answer": False})


def run_turn(chat_id, uid, text):
    """One full agent turn on a worker thread (approvals block here)."""
    sess = get_sess(chat_id)
    sess["busy"] = True
    try:
        udir = user_dir(uid)
        engine_tools.set_workspace(os.path.join(udir, "workspace"))
        mem = Memory(os.path.join(udir, "memory.json"))
        brain = RouterBrain()
        if not brain.configured():
            brain = DemoBrain()
        agent = Agent(brain, mem)

        if text.startswith("মনে রাখো:"):
            fact = text.replace("মনে রাখো:", "").strip()
            if ":" in fact:
                k, v = fact.split(":", 1)
                mem.remember(k.strip(), v.strip())
                insert_msg(chat_id, "agent", "মনে রাখলাম ✅")
            else:
                insert_msg(chat_id, "agent", "ফরম্যাট — মনে রাখো: বিষয়: তথ্য")
            return

        conn = db()
        row = conn.execute("SELECT hist, title FROM chats WHERE id=?",
                           (chat_id,)).fetchone()
        hist = json.loads(row["hist"] or "[]") if row else []
        if row and row["title"] == "নতুন চ্যাট":
            conn.execute("UPDATE chats SET title=? WHERE id=?",
                         (text[:42], chat_id))
            conn.commit()
        conn.close()

        def approve(name, level, args):
            sess["approval"] = {"text": "⚠️ এজেন্ট করতে চায়: %s (%s)\n%s"
                                % (name, level, str(args)[:300])}
            sess["event"].clear()
            got = sess["event"].wait(timeout=600)
            sess["approval"] = None
            return bool(got and sess["answer"])

        def notify(t):
            insert_msg(chat_id, "tool", t)

        reply = agent.run(text, approve, notify, history=hist)
        insert_msg(chat_id, "agent", reply)
        tu = getattr(agent, "turn_usage", None)
        if tu and tu.get("total"):
            line = ("🪙 এই কাজে টোকেন খরচ: ~{:,} (ইন {:,} + আউট {:,})"
                    .format(tu["total"], tu["prompt"], tu["completion"]))
            bp = getattr(agent.brain, "last_provider", None)
            if bp:
                line += " • 🧠 %s/%s" % (bp, getattr(agent.brain,
                                                     "last_model", ""))
                kn = getattr(agent.brain, "last_key_no", None)
                if kn:
                    line += " · key #%s" % kn
            insert_msg(chat_id, "system", line)
        hist = (hist + [{"role": "user", "content": text},
                        {"role": "assistant", "content": reply}])[-20:]
        conn = db()
        conn.execute("UPDATE chats SET hist=? WHERE id=?",
                     (json.dumps(hist, ensure_ascii=False), chat_id))
        conn.commit()
        conn.close()
    except Exception as e:
        insert_msg(chat_id, "system", "সমস্যা হয়েছে: %s" % e)
    finally:
        sess["busy"] = False


def gen_code():
    alpha = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    part = lambda: "".join(secrets.choice(alpha) for _ in range(4))
    return "KD-%s-%s-%s" % (part(), part(), part())


# ---------- HTTP handler --------------------------------------------------
MIME = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
        ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml",
        ".ico": "image/x-icon"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # CORS + Private-Network-Access: hosted UI (browser) যাতে এই
        # PC-র লোকাল ইঞ্জিনকে ডাকতে পারে। আসল কাজ token ছাড়া হয় না।
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def _auth(self):
        tok = (self.headers.get("Authorization") or "").replace("Bearer ", "")
        uid = parse_token(tok) if tok else None
        if not uid:
            return None
        conn = db()
        user = get_user(conn, uid)
        conn.close()
        return user

    # ----- API -----
    def do_POST(self):
        p = self.path
        d = self._body()
        conn = db()
        try:
            if p == "/api/register":
                name = (d.get("name") or "").strip()
                email = (d.get("email") or "").strip().lower()
                pw = d.get("password") or ""
                if not name or "@" not in email or len(pw) < 6:
                    return self._send(400, {"error": "নাম, সঠিক ইমেইল আর "
                                            "কমপক্ষে ৬ অক্ষরের পাসওয়ার্ড দাও"})
                if conn.execute("SELECT id FROM users WHERE email=?",
                                (email,)).fetchone():
                    return self._send(400, {"error": "এই ইমেইলে আগেই "
                                            "অ্যাকাউন্ট আছে — লগইন করো"})
                salt, hashed = hash_pw(pw)
                cur = conn.execute(
                    "INSERT INTO users(name,email,pw,salt,role,created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (name, email, hashed, salt, "user", now_iso()))
                conn.execute("INSERT INTO subscriptions(user_id,plan) "
                             "VALUES(?,'free')", (cur.lastrowid,))
                conn.commit()
                return self._send(200, {"token": make_token(cur.lastrowid),
                                        "name": name})

            if p == "/api/login":
                email = (d.get("email") or "").strip().lower()
                pw = d.get("password") or ""
                u = conn.execute("SELECT * FROM users WHERE email=?",
                                 (email,)).fetchone()
                if not u:
                    return self._send(401, {"error": "অ্যাকাউন্ট পাইনি"})
                _, hashed = hash_pw(pw, u["salt"])
                if not hmac.compare_digest(hashed, u["pw"]):
                    return self._send(401, {"error": "পাসওয়ার্ড মিললো না"})
                return self._send(200, {"token": make_token(u["id"]),
                                        "name": u["name"]})

            user = self._auth()
            if not user:
                return self._send(401, {"error": "লগইন লাগবে"})
            uid = user["id"]

            if p == "/api/redeem":
                code = (d.get("code") or "").strip().upper()
                k = conn.execute("SELECT * FROM keys WHERE code=?",
                                 (code,)).fetchone()
                if not k or k["revoked"]:
                    return self._send(400, {"error": "key-টা সঠিক না"})
                if k["used_by"]:
                    return self._send(400, {"error": "এই key আগেই ব্যবহৃত"})
                plan, days = k["plan"], k["days"]
                _, cur_exp, _ = user_plan(conn, uid)
                base = datetime.now(timezone.utc)
                if cur_exp:
                    e = datetime.fromisoformat(cur_exp)
                    if e > base:
                        base = e
                expires = (base + timedelta(days=days)).isoformat(
                    timespec="seconds")
                conn.execute("UPDATE keys SET used_by=?, used_at=? "
                             "WHERE id=?", (uid, now_iso(), k["id"]))
                conn.execute("INSERT INTO subscriptions(user_id,plan,"
                             "expires_at) VALUES(?,?,?) ON CONFLICT(user_id) "
                             "DO UPDATE SET plan=?, expires_at=?",
                             (uid, plan, expires, plan, expires))
                conn.commit()
                return self._send(200, {"ok": True, "plan": plan,
                                        "expires_at": expires})

            if p == "/api/chats":
                cur = conn.execute(
                    "INSERT INTO chats(user_id,created_at) VALUES(?,?)",
                    (uid, now_iso()))
                conn.commit()
                return self._send(200, {"id": cur.lastrowid})

            parts = p.strip("/").split("/")
            if (len(parts) == 4 and parts[:2] == ["api", "chats"]
                    and parts[3] in ("send", "approve")):
                chat_id = int(parts[2])
                own = conn.execute(
                    "SELECT id FROM chats WHERE id=? AND user_id=?",
                    (chat_id, uid)).fetchone()
                if not own:
                    return self._send(404, {"error": "চ্যাট পাইনি"})
                sess = get_sess(chat_id)
                if parts[3] == "approve":
                    sess["answer"] = bool(d.get("ok"))
                    sess["event"].set()
                    return self._send(200, {"ok": True})
                text = (d.get("text") or "").strip()
                if not text:
                    return self._send(400, {"error": "খালি মেসেজ"})
                if sess["busy"]:
                    return self._send(409, {"error": "এজেন্ট আগের কাজে ব্যস্ত"})
                plan, _, _ = user_plan(conn, uid)
                limit = PLANS[plan]["daily"]
                if usage_today(conn, uid) >= limit:
                    return self._send(429, {"error": "আজকের কোটা শেষ (%d) — "
                                            "Pro প্ল্যানে বেশি পাবে!" % limit})
                bump_usage(conn, uid)
                insert_msg(chat_id, "user", text)
                threading.Thread(target=run_turn,
                                 args=(chat_id, uid, text),
                                 daemon=True).start()
                return self._send(200, {"ok": True})

            if p == "/api/files/upload":
                name = os.path.basename((d.get("name") or "").strip())
                if not name or not d.get("content_b64"):
                    return self._send(400, {"error": "ফাইল লাগবে"})
                try:
                    raw = base64.b64decode(d["content_b64"])
                except Exception:
                    return self._send(400, {"error": "বাজে ডাটা"})
                if len(raw) > 5 * 1024 * 1024:
                    return self._send(400, {"error": "৫MB-এর বেশি না"})
                ws = os.path.join(user_dir(uid), "workspace")
                with open(os.path.join(ws, name), "wb") as f:
                    f.write(raw)
                return self._send(200, {"ok": True, "name": name})

            if p.startswith("/api/admin/"):
                if user["role"] != "admin":
                    return self._send(403, {"error": "admin ছাড়া হবে না"})
                if p == "/api/admin/keys":
                    plan = d.get("plan", "pro")
                    days = int(d.get("days", 30))
                    count = min(int(d.get("count", 1)), 50)
                    if plan not in PLANS or plan == "free":
                        return self._send(400, {"error": "plan ভুল"})
                    codes = []
                    for _ in range(count):
                        code = gen_code()
                        conn.execute("INSERT INTO keys(code,plan,days,"
                                     "created_at) VALUES(?,?,?,?)",
                                     (code, plan, days, now_iso()))
                        codes.append(code)
                    conn.commit()
                    return self._send(200, {"codes": codes})
                if p == "/api/admin/revoke":
                    conn.execute("UPDATE keys SET revoked=1 WHERE code=?",
                                 ((d.get("code") or "").strip().upper(),))
                    conn.commit()
                    return self._send(200, {"ok": True})
                return self._send(404, {"error": "not found"})

            return self._send(404, {"error": "not found"})
        finally:
            conn.close()

    def do_GET(self):
        p = self.path.split("?")[0]
        conn = db()
        try:
            if p == "/api/plans":
                return self._send(200, {"plans": PLANS})
            if p == "/api/me":
                user = self._auth()
                if not user:
                    return self._send(401, {"error": "লগইন লাগবে"})
                plan, exp, active = user_plan(conn, user["id"])
                return self._send(200, {
                    "name": user["name"], "email": user["email"],
                    "role": user["role"], "plan": plan,
                    "plan_name": PLANS[plan]["name"],
                    "expires_at": exp, "sub_active": active,
                    "used": usage_today(conn, user["id"]),
                    "limit": PLANS[plan]["daily"],
                    "brain": brain_mode(),
                    "brain_info": RouterBrain().describe(),
                    "brain_chain": RouterBrain().chain()})
            if p == "/api/admin/users":
                user = self._auth()
                if not user or user["role"] != "admin":
                    return self._send(403, {"error": "admin ছাড়া হবে না"})
                rows = conn.execute(
                    "SELECT u.id,u.name,u.email,u.role,u.created_at,"
                    "s.plan,s.expires_at FROM users u LEFT JOIN "
                    "subscriptions s ON s.user_id=u.id ORDER BY u.id").fetchall()
                return self._send(200, {"users": [dict(r) for r in rows]})
            if p == "/api/admin/keys":
                user = self._auth()
                if not user or user["role"] != "admin":
                    return self._send(403, {"error": "admin ছাড়া হবে না"})
                rows = conn.execute("SELECT * FROM keys ORDER BY id DESC "
                                    "LIMIT 100").fetchall()
                return self._send(200, {"keys": [dict(r) for r in rows]})
            if p == "/api/chats":
                user = self._auth()
                if not user:
                    return self._send(401, {"error": "লগইন লাগবে"})
                rows = conn.execute(
                    "SELECT id,title,created_at FROM chats WHERE user_id=? "
                    "ORDER BY id DESC", (user["id"],)).fetchall()
                return self._send(200, {"chats": [dict(r) for r in rows]})
            parts = p.strip("/").split("/")
            if (len(parts) == 4 and parts[:2] == ["api", "chats"]
                    and parts[3] == "poll"):
                user = self._auth()
                if not user:
                    return self._send(401, {"error": "লগইন লাগবে"})
                chat_id = int(parts[2])
                own = conn.execute(
                    "SELECT id FROM chats WHERE id=? AND user_id=?",
                    (chat_id, user["id"])).fetchone()
                if not own:
                    return self._send(404, {"error": "চ্যাট পাইনি"})
                q = urllib.parse.parse_qs(
                    urllib.parse.urlparse(self.path).query)
                since = int((q.get("since") or ["0"])[0])
                rows = conn.execute(
                    "SELECT id,who,text FROM chat_msgs WHERE chat_id=? "
                    "AND id>? ORDER BY id", (chat_id, since)).fetchall()
                sess = get_sess(chat_id)
                return self._send(200, {
                    "msgs": [dict(r) for r in rows], "busy": sess["busy"],
                    "approval": sess["approval"],
                    "used": usage_today(conn, user["id"])})
            if p == "/api/files":
                user = self._auth()
                if not user:
                    return self._send(401, {"error": "লগইন লাগবে"})
                ws = os.path.join(user_dir(user["id"]), "workspace")
                out = []
                for dp, dns, fns in os.walk(ws):
                    dns[:] = [d for d in dns if not d.startswith(".")]
                    for fn in fns:
                        if fn.startswith("."):
                            continue
                        fp = os.path.join(dp, fn)
                        out.append({"path": os.path.relpath(fp, ws),
                                    "size": os.path.getsize(fp)})
                        if len(out) >= 300:
                            break
                return self._send(200, {"files": out})
            if p == "/api/files/download":
                user = self._auth()
                if not user:
                    return self._send(401, {"error": "লগইন লাগবে"})
                q = urllib.parse.parse_qs(
                    urllib.parse.urlparse(self.path).query)
                rel = (q.get("path") or [""])[0]
                ws = os.path.join(user_dir(user["id"]), "workspace")
                fp = os.path.abspath(os.path.join(ws, rel))
                if not fp.startswith(ws) or not os.path.isfile(fp):
                    return self._send(404, {"error": "ফাইল পাইনি"})
                with open(fp, "rb") as f:
                    return self._send(200, f.read(),
                                      "application/octet-stream")
            # static files
            if p == "/":
                p = "/index.html"
            fp = os.path.normpath(os.path.join(WEB, p.lstrip("/")))
            if not fp.startswith(WEB) or not os.path.isfile(fp):
                return self._send(404, "not found", "text/plain")
            ext = os.path.splitext(fp)[1]
            with open(fp, "rb") as f:
                return self._send(200, f.read(),
                                  MIME.get(ext, "application/octet-stream"))
        finally:
            conn.close()


def main():
    init_db()
    port = PORT
    while True:
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
            break
        except OSError:
            port += 1  # port busy hole porer ta nebe
            if port > PORT + 20:
                raise
    url = "http://127.0.0.1:%d" % port
    print("🌐 Kamla Dei প্ল্যাটফর্ম চালু: %s" % url)
    print("   Brain: %s" % (("LIVE — " + RouterBrain().chain())
                            if brain_mode() == "live"
                            else "ডেমো মোড (কোনো API key env নেই)"))
    if os.environ.get("KAMLA_NO_BROWSER") != "1":
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
