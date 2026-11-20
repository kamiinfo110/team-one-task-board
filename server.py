#!/usr/bin/env python3
"""Team One — shared task board, single-file Python stdlib server.
No dependencies. Data in db.json next to this file.
Test logins only — change passwords before real use.
"""
import json, os, hashlib, secrets, datetime, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "db.json")
PORT = int(os.environ.get("PORT") or os.environ.get("TEAM_ONE_PORT", "8765"))

MEMBERS = [
    ("rauf", "Muhammad Rauf", True, "rauf123"),
    ("kamran", "Kamran Khan", False, "kamran123"),
    ("ishtiaq", "Ishtiaq Ahmed", False, "ishtiaq123"),
    ("umar", "Muhammad Umar", False, "umar123"),
    ("amar", "Muhammad Amar", False, "amar123"),
    ("danish", "Muhammad Danish", False, "danish123"),
    ("wilayatullah", "Wilayatullah", False, "wilayatullah123"),
]

def pw_hash(pw):
    return hashlib.sha256(("team-one:" + pw).encode()).hexdigest()

def default_db():
    return {
        "users": [
            {"username": u, "name": n, "leader": l, "password_hash": pw_hash(p)}
            for u, n, l, p in MEMBERS
        ],
        "tasks": [],
        "next_task_id": 1,
    }

def load_db():
    if not os.path.exists(DB_PATH):
        db = default_db()
        save_db(db)
        return db
    with open(DB_PATH) as f:
        return json.load(f)

def save_db(db):
    tmp = DB_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(db, f, indent=2)
    os.replace(tmp, DB_PATH)

SESSIONS = {}  # token -> {"username":..., "expires": iso}

def today_str():
    return datetime.date.today().isoformat()

def public_task(t, users):
    name = {u["username"]: u["name"] for u in users}
    overdue = t["status"] in ("Pending", "In Progress") and t["due_date"] < today_str()
    return {**t, "assigned_name": name.get(t["assigned_to"], t["assigned_to"]),
            "assigned_by_name": name.get(t["assigned_by"], t["assigned_by"]),
            "overdue": overdue}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj=None, ctype="application/json"):
        body = b"" if obj is None else (obj if isinstance(obj, bytes) else json.dumps(obj).encode())
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.wfile:
            self.wfile.write(body)

    def _cookie_user(self):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("teamone="):
                tok = part[len("teamone="):]
                s = SESSIONS.get(tok)
                if s:
                    db = load_db()
                    for u in db["users"]:
                        if u["username"] == s["username"]:
                            return u
        return None

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw.decode() or "{}")
        except Exception:
            return {}

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(BASE, "index.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
            return
        if self.path == "/api/me":
            u = self._cookie_user()
            if not u:
                return self._send(401, {"error": "not logged in"})
            return self._send(200, {"username": u["username"], "name": u["name"], "leader": u["leader"]})
        if self.path == "/api/board":
            u = self._cookie_user()
            if not u:
                return self._send(401, {"error": "not logged in"})
            db = load_db()
            members = [{"username": x["username"], "name": x["name"], "leader": x["leader"]} for x in db["users"]]
            tasks = [public_task(t, db["users"]) for t in sorted(db["tasks"], key=lambda t: (t["status"] == "Done", t["due_date"], t["id"]))]
            return self._send(200, {"me": {"username": u["username"], "name": u["name"], "leader": u["leader"]},
                                   "members": members, "tasks": tasks, "today": today_str()})
        if self.path == "/api/health":
            return self._send(200, {"ok": True, "team": "Team One", "today": today_str()})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        db = load_db()
        if self.path == "/api/login":
            b = self._body()
            user = next((x for x in db["users"] if x["username"] == str(b.get("username", "")).strip().lower()), None)
            if not user or user["password_hash"] != pw_hash(str(b.get("password", ""))):
                return self._send(401, {"error": "Wrong username or password"})
            tok = secrets.token_hex(24)
            SESSIONS[tok] = {"username": user["username"]}
            body = json.dumps({"ok": True, "name": user["name"], "leader": user["leader"]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", f"teamone={tok}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/logout":
            self._send(200, {"ok": True})
            return
        u = self._cookie_user()
        if not u:
            return self._send(401, {"error": "not logged in"})
        b = self._body()
        if self.path == "/api/tasks":
            if not u["leader"]:
                return self._send(403, {"error": "Only the leader can assign tasks"})
            title = str(b.get("title", "")).strip()
            assigned = str(b.get("assigned_to", "")).strip()
            due = str(b.get("due_date", "")).strip()
            if not title or not assigned or not due:
                return self._send(400, {"error": "Title, assigned member and due date are all required"})
            if not any(x["username"] == assigned for x in db["users"]):
                return self._send(400, {"error": "Unknown member"})
            try:
                datetime.date.fromisoformat(due)
            except ValueError:
                return self._send(400, {"error": "Due date must be a real date"})
            t = {"id": db["next_task_id"], "title": title,
                 "description": str(b.get("description", "")).strip(),
                 "assigned_to": assigned, "assigned_by": u["username"],
                 "due_date": due, "status": "Pending",
                 "submission": "", "submission_link": "", "created": today_str(), "history": []}
            db["next_task_id"] += 1
            db["tasks"].append(t)
            save_db(db)
            return self._send(200, {"ok": True, "task": public_task(t, db["users"])})
        # /api/tasks/<id>/<action>
        parts = self.path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "tasks":
            try:
                tid = int(parts[2])
            except ValueError:
                return self._send(400, {"error": "bad task id"})
            action = parts[3]
            t = next((x for x in db["tasks"] if x["id"] == tid), None)
            if not t:
                return self._send(404, {"error": "task not found"})
            if action == "start":
                if t["assigned_to"] != u["username"] and not u["leader"]:
                    return self._send(403, {"error": "Only the assigned member can start this task"})
                if t["status"] != "Pending":
                    return self._send(400, {"error": "Task is not Pending"})
                t["status"] = "In Progress"
            elif action == "submit":
                if t["assigned_to"] != u["username"]:
                    return self._send(403, {"error": "Only the assigned member can submit this task"})
                if t["status"] == "Done":
                    return self._send(400, {"error": "Task is already Done"})
                note = str(b.get("submission", "")).strip()
                if not note and not str(b.get("submission_link", "")).strip():
                    return self._send(400, {"error": "Write what you did, or add a link, to submit"})
                t["submission"] = note
                t["submission_link"] = str(b.get("submission_link", "")).strip()
                t["status"] = "Submitted"
            elif action == "done":
                if not u["leader"]:
                    return self._send(403, {"error": "Only the leader can mark Done"})
                t["status"] = "Done"
            elif action == "sendback":
                if not u["leader"]:
                    return self._send(403, {"error": "Only the leader can send a task back"})
                t["status"] = "In Progress"
                t["history"].append(f"Sent back by leader on {today_str()}: {str(b.get('note','')).strip()}")
            elif action == "delete":
                if not u["leader"]:
                    return self._send(403, {"error": "Only the leader can delete a task"})
                db["tasks"] = [x for x in db["tasks"] if x["id"] != tid]
                save_db(db)
                return self._send(200, {"ok": True})
            else:
                return self._send(404, {"error": "unknown action"})
            save_db(db)
            return self._send(200, {"ok": True, "task": public_task(t, db["users"])})
        if self.path == "/api/change-password":
            new = str(b.get("new_password", "")).strip()
            target = str(b.get("username", "")).strip() or u["username"]
            if len(new) < 4:
                return self._send(400, {"error": "Password must be at least 4 characters"})
            if target != u["username"] and not u["leader"]:
                return self._send(403, {"error": "Only the leader can change another member's password"})
            target_user = next((x for x in db["users"] if x["username"] == target), None)
            if not target_user:
                return self._send(404, {"error": "Unknown member"})
            target_user["password_hash"] = pw_hash(new)
            save_db(db)
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})

if __name__ == "__main__":
    load_db()
    print(f"Team One running on http://0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
