"""Coding tools for the agent. Everything is sandboxed to the workspace folder.

Risk levels (mirrors the blueprint's approval model):
    green  — read-only, runs freely
    yellow — writes files, asks once per session then remembered
    red    — shell / delete / outside contact, asks EVERY time
"""
import contextvars
import html as htmlmod
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "workspace"))

# Per-user workspace (server mode): the app sets this per agent turn.
_WS = contextvars.ContextVar("kamla_workspace", default="")

def _ws():
    return _WS.get() or WORKSPACE

def set_workspace(path):
    os.makedirs(path, exist_ok=True)
    _WS.set(os.path.abspath(path))

# Commands the agent may never run, even with approval.
BLOCKED_SHELL = [
    r"\brm\s+-rf\s+/(?:\s|$)",   # rm -rf /
    r":\(\)\s*\{",               # fork bomb
    r"\bmkfs\b",
    r"\bdd\s+.*of=/dev/",
    r">\s*/dev/sd",
]


def _safe_path(path):
    root = _ws()
    p = os.path.abspath(os.path.join(root, path or "."))
    if p != root and not p.startswith(root + os.sep):
        raise ValueError("workspace-এর বাইরে যাওয়া যাবে না")
    return p


# ---------------- implementations ----------------

def tool_read_file(path):
    p = _safe_path(path)
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        data = f.read()
    if len(data) > 4000:
        return data[:4000] + "\n…[ফাইল আরও বড় — বাকিটা দরকার হলে search_files দিয়ে খোঁজো]"
    return data


def tool_write_file(path, content):
    p = _safe_path(path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return "OK: %d chars written to %s" % (len(content), path)


def tool_edit_file(path, old_text, new_text):
    p = _safe_path(path)
    with open(p, "r", encoding="utf-8") as f:
        content = f.read()
    if old_text not in content:
        return "ERROR: old_text পাওয়া যায়নি"
    content = content.replace(old_text, new_text, 1)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return "OK: edited"


def tool_list_dir(path="."):
    p = _safe_path(path)
    return "\n".join(sorted(os.listdir(p)))


def _fix_python_cmd(command):
    """'python ...' -> এজেন্টের নিজের (bundled) interpreter।

    Windows-এ খালি 'python' লিখলে Microsoft Store-এর ভুয়া alias ধরে
    (exit 9009) — এজেন্ট সবসময় নিজের Python-ই ব্যবহার করবে।
    """
    exe = '"%s"' % sys.executable
    return re.sub(r"(^|[&;|]\s*)python3?\b",
                  lambda m: m.group(1) + exe, command)


def _clip(out, limit=2600):
    """লম্বা আউটপুটের মাঝখান কেটে টোকেন বাঁচাই (শুরু+শেষ থাকে)।"""
    if len(out) <= limit:
        return out
    return out[:1800] + "\n…[মাঝের অংশ কেটে দেওয়া হয়েছে]…\n" + out[-700:]


def _utf8_env():
    """Child processes must speak UTF-8 — Windows consoles (cp1252)
    crash on Bengali print() without this."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def tool_run_shell(command, timeout=30):
    for pat in BLOCKED_SHELL:
        if re.search(pat, command):
            return "ERROR: এই কমান্ড চালানো নিষেধ"
    command = _fix_python_cmd(command)
    try:
        proc = subprocess.run(
            command, shell=True, cwd=_ws(), env=_utf8_env(),
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return "[exit %d]\n%s" % (proc.returncode, _clip(out))
    except subprocess.TimeoutExpired:
        return "ERROR: কমান্ডের সময় শেষ"


def tool_web_search(query):
    try:
        q = urllib.parse.quote(query)
        req = urllib.request.Request(
            "https://html.duckduckgo.com/html/?q=" + q,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            page = r.read().decode("utf-8", "replace")
        hits = re.findall(
            r'class="result__a"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
            page, re.S,
        )
        lines = []
        for title, snip in hits[:5]:
            t = re.sub(r"<.*?>", "", title).strip()
            s = htmlmod.unescape(re.sub(r"<.*?>", "", snip)).strip()
            lines.append("- %s: %s" % (t, s))
        return "\n".join(lines) if lines else "কোনো রেজাল্ট পাইনি"
    except Exception as e:
        return "সার্চ ব্যর্থ: %s" % e


# ---------------- registry ----------------

def tool_search_files(pattern, path=".", case_sensitive=False):
    """Workspace-এর ফাইলগুলোর ভেতরে text খোঁজা (grep-এর মতো)।"""
    root = _safe_path(path)
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        rx = re.compile(pattern, flags)
    except re.error:
        rx = re.compile(re.escape(pattern), flags)
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.startswith("."):
                continue
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, _ws())
            if rx.search(fn):
                hits.append("%s (ফাইলের নামে মিল)" % rel)
            try:
                if os.path.getsize(fp) > 2 * 1024 * 1024:
                    continue
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if rx.search(line):
                            rel = os.path.relpath(fp, _ws())
                            hits.append("%s:%d: %s" % (rel, i, line.strip()[:120]))
                            if len(hits) >= 40:
                                return "\n".join(hits) + "\n... (আরও আছে)"
            except OSError:
                continue
    return "\n".join(hits) if hits else "কিছু পাইনি"


def tool_fetch_url(url, max_chars=8000):
    """ওয়েবপেজের লেখা পড়া — ডকুমেন্টেশন, উদাহরণ দেখতে।"""
    if not re.match(r"^https?://", url.strip()):
        return "ERROR: শুধু http/https URL"
    try:
        req = urllib.request.Request(url.strip(), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read(200000).decode("utf-8", "replace")
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw,
                      flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = htmlmod.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars] if text else "পেজ খালি"
    except Exception as e:
        return "আনা যায়নি: %s" % e


def tool_get_time():
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def tool_make_dir(path):
    p = _safe_path(path)
    os.makedirs(p, exist_ok=True)
    return "OK: ফোল্ডার রেডি"


def tool_move_file(src, dst):
    import shutil
    s, d = _safe_path(src), _safe_path(dst)
    if not os.path.exists(s):
        return "ERROR: source ফাইল নেই"
    os.makedirs(os.path.dirname(d), exist_ok=True)
    shutil.move(s, d)
    return "OK: সরানো হয়েছে"


def tool_delete_file(path):
    p = _safe_path(path)
    if not os.path.isfile(p):
        return "ERROR: ফাইল নেই"
    os.remove(p)
    return "OK: ডিলিট হয়েছে"


TOOLS = {
    "read_file":  {"fn": tool_read_file,  "level": "green"},
    "list_dir":   {"fn": tool_list_dir,   "level": "green"},
    "web_search": {"fn": tool_web_search, "level": "green"},
    "search_files": {"fn": tool_search_files, "level": "green"},
    "fetch_url":  {"fn": tool_fetch_url,  "level": "green"},
    "get_time":   {"fn": tool_get_time,   "level": "green"},
    "write_file": {"fn": tool_write_file, "level": "yellow"},
    "edit_file":  {"fn": tool_edit_file,  "level": "yellow"},
    "make_dir":   {"fn": tool_make_dir,   "level": "yellow"},
    "move_file":  {"fn": tool_move_file,  "level": "yellow"},
    "run_shell":  {"fn": tool_run_shell,  "level": "red"},
    "delete_file": {"fn": tool_delete_file, "level": "red"},
}

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file inside the workspace.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Relative path inside workspace"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "List files in a workspace directory.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Relative dir, default '.'"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web for docs, errors, examples.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or overwrite a file inside the workspace.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Replace one exact old_text with new_text in a file.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"}},
            "required": ["path", "old_text", "new_text"]}}},
    {"type": "function", "function": {
        "name": "run_shell",
        "description": "Run a shell command INSIDE the workspace only. Dangerous commands are blocked.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "e.g. 'python hello.py' or 'pip install requests'"},
            "timeout": {"type": "integer", "default": 30}},
            "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "search_files",
        "description": "Search text inside workspace files (like grep).",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "Text or regex to find"},
            "path": {"type": "string", "default": "."},
            "case_sensitive": {"type": "boolean", "default": False}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "fetch_url",
        "description": "Read a web page as text (docs, examples). http/https only.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"},
            "max_chars": {"type": "integer", "default": 8000}},
            "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "get_time",
        "description": "Current date and time.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "make_dir",
        "description": "Create a folder inside the workspace.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "move_file",
        "description": "Move/rename a file inside the workspace.",
        "parameters": {"type": "object", "properties": {
            "src": {"type": "string"},
            "dst": {"type": "string"}},
            "required": ["src", "dst"]}}},
    {"type": "function", "function": {
        "name": "delete_file",
        "description": "Delete a file inside the workspace. Asks every time.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}},
            "required": ["path"]}}},
]


# ================= ধাপ-১: system / communication / convenience =================

def tool_run_python(code, timeout=30):
    """Python কোড সরাসরি চালানো (ফাইল না বানিয়েই)।"""
    p = os.path.join(_ws(), ".agent_run.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write(code)
    try:
        proc = subprocess.run([sys.executable, p], cwd=_ws(), env=_utf8_env(),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
        return "[exit %d]\n%s" % (proc.returncode, _clip(out))
    except subprocess.TimeoutExpired:
        return "ERROR: সময় শেষ"


def _ram_gb():
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            ms = MS()
            ms.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            return round(ms.ullTotalPhys / 1e9, 1)
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1e6, 1)
    except Exception:
        pass
    return "unknown"


def tool_get_system_info():
    """PC-র তথ্য: OS, CPU, RAM, ফাঁকা ডিস্ক।"""
    import platform
    info = [("os", platform.system() + " " + platform.release()),
            ("machine", platform.machine()),
            ("cpu", os.cpu_count()),
            ("ram_gb", _ram_gb())]
    try:
        d = shutil.disk_usage(_ws())
        info.append(("disk_free_gb", round(d.free / 1e9, 1)))
    except Exception:
        pass
    return "\n".join("%s: %s" % kv for kv in info)


def tool_open_target(target):
    """ফাইল/ওয়েবসাইট/অ্যাপ ডিফল্ট প্রোগ্রামে খোলা।"""
    t = target.strip()
    if os.environ.get("KAMLA_SERVER") == "1":
        if t.startswith("http://") or t.startswith("https://"):
            return "লিংক: %s (ব্রাউজারে খোলো)" % t
        return "ফাইল '%s' — 📁 Files প্যানেল থেকে ডাউনলোড করতে পারো" % t
    try:
        if os.name == "nt":
            os.startfile(t)
        elif sys.platform == "darwin":
            subprocess.run(["open", t], timeout=15)
        else:
            subprocess.run(["xdg-open", t], timeout=15)
        return "OK: খোলা হয়েছে"
    except Exception as e:
        return "খোলা যায়নি: %s" % e


def tool_send_email(to, subject, body):
    """ইমেইল পাঠানো (SMTP)। AGENT_SMTP_* সেটআপ লাগে — README দেখো।"""
    import smtplib
    from email.message import EmailMessage
    host = os.environ.get("AGENT_SMTP_HOST", "").strip()
    try:
        port = int(os.environ.get("AGENT_SMTP_PORT", "587"))
    except ValueError:
        port = 587
    user = os.environ.get("AGENT_SMTP_USER", "").strip()
    pw = os.environ.get("AGENT_SMTP_PASS", "")
    if not (host and user and pw):
        return ("ERROR: SMTP সেটআপ নেই। AGENT_SMTP_HOST / AGENT_SMTP_PORT / "
                "AGENT_SMTP_USER / AGENT_SMTP_PASS সেট করো (README দেখো)।")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", to.strip()):
        return "ERROR: ঠিকানা ঠিক নয়"
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to.strip()
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
        return "OK: ইমেইল পাঠানো হয়েছে"
    except Exception as e:
        return "পাঠানো যায়নি: %s" % e


def tool_notify(title, message):
    """PC-তে নোটিফিকেশন দেখানো।"""
    t = title.replace("'", "''")[:64]
    m = message.replace("'", "''")[:256]
    try:
        if os.name == "nt":
            ps = ("Add-Type -AssemblyName System.Windows.Forms; "
                  "$n = New-Object System.Windows.Forms.NotifyIcon; "
                  "$n.Icon = [System.Drawing.SystemIcons]::Information; "
                  "$n.BalloonTipTitle = '%s'; $n.BalloonTipText = '%s'; "
                  "$n.Visible = $true; $n.ShowBalloonTip(5000); "
                  "Start-Sleep -Seconds 6; $n.Dispose()" % (t, m))
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=25)
            return "OK: নোটিফিকেশন দেখানো হয়েছে"
    except Exception:
        pass
    return "NOTIFY [%s]: %s" % (title, message)


def tool_clipboard_read():
    """ক্লিপবোর্ডের লেখা পড়া।"""
    try:
        if os.name == "nt":
            p = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "Get-Clipboard -Raw"],
                               capture_output=True, text=True, timeout=15)
            return p.stdout.strip() or "(খালি)"
        for cmd in (["xclip", "-o", "-selection", "clipboard"],
                    ["xsel", "--clipboard", "--output"]):
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if p.returncode == 0:
                    return p.stdout or "(খালি)"
            except FileNotFoundError:
                continue
        return "clipboard পড়া যায়নি"
    except Exception as e:
        return "পড়া যায়নি: %s" % e


def tool_clipboard_write(text):
    """ক্লিপবোর্ডে লেখা কপি করা।"""
    try:
        if os.name == "nt":
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            "$input | Set-Clipboard"],
                           input=text, capture_output=True, text=True, timeout=15)
            return "OK: কপি হয়েছে"
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text, capture_output=True,
                           text=True, timeout=10)
            return "OK: কপি হয়েছে"
        for cmd in (["xclip", "-selection", "clipboard"],
                    ["xsel", "--clipboard", "--input"]):
            try:
                subprocess.run(cmd, input=text, capture_output=True,
                               text=True, timeout=10)
                return "OK: কপি হয়েছে"
            except FileNotFoundError:
                continue
        return "clipboard-এ লেখা যায়নি"
    except Exception as e:
        return "কপি ব্যর্থ: %s" % e


def tool_download_file(url, dest, max_mb=50):
    """ওয়েব থেকে ফাইল ডাউনলোড করে workspace-এ রাখা।"""
    if not re.match(r"^https?://", url.strip()):
        return "ERROR: শুধু http/https"
    p = _safe_path(dest)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        req = urllib.request.Request(url.strip(),
                                     headers={"User-Agent": "Mozilla/5.0"})
        total = 0
        with urllib.request.urlopen(req, timeout=60) as r:
            with open(p, "wb") as f:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_mb * 1024 * 1024:
                        f.close()
                        os.remove(p)
                        return "ERROR: %dMB-এর বেশি বড়" % max_mb
                    f.write(chunk)
        return "OK: %d bytes -> %s" % (total, dest)
    except Exception as e:
        return "ডাউনলোড ব্যর্থ: %s" % e


TOOLS.update({
    "run_python":     {"fn": tool_run_python,     "level": "red"},
    "get_system_info": {"fn": tool_get_system_info, "level": "green"},
    "open_target":    {"fn": tool_open_target,    "level": "yellow"},
    "send_email":     {"fn": tool_send_email,     "level": "red"},
    "notify":         {"fn": tool_notify,         "level": "green"},
    "clipboard_read": {"fn": tool_clipboard_read, "level": "yellow"},
    "clipboard_write": {"fn": tool_clipboard_write, "level": "green"},
    "download_file":  {"fn": tool_download_file,  "level": "yellow"},
})

TOOL_SCHEMAS.extend([
    {"type": "function", "function": {
        "name": "run_python",
        "description": "Run Python code directly and return output.",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string"},
            "timeout": {"type": "integer", "default": 30}},
            "required": ["code"]}}},
    {"type": "function", "function": {
        "name": "get_system_info",
        "description": "PC info: OS, CPU, RAM, free disk.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "open_target",
        "description": "Open a file, website or app with the default program.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "Path, URL or app name"}},
            "required": ["target"]}}},
    {"type": "function", "function": {
        "name": "send_email",
        "description": "Send an email via SMTP (needs AGENT_SMTP_* setup).",
        "parameters": {"type": "object", "properties": {
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"}},
            "required": ["to", "subject", "body"]}}},
    {"type": "function", "function": {
        "name": "notify",
        "description": "Show a PC notification.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"},
            "message": {"type": "string"}},
            "required": ["title", "message"]}}},
    {"type": "function", "function": {
        "name": "clipboard_read",
        "description": "Read clipboard text.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "clipboard_write",
        "description": "Copy text to clipboard.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}},
            "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "download_file",
        "description": "Download a file from the web into the workspace.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"},
            "dest": {"type": "string", "description": "Relative path in workspace"},
            "max_mb": {"type": "integer", "default": 50}},
            "required": ["url", "dest"]}}},
])


# ================= Inbuilt Linux (WSL2/Ubuntu) =================
# setup-linux.ps1 chalale user-er PC-te Ubuntu ready hoy.
# Tarpor agent linux_run diye asol Linux-e kaj korte pare.

def _wsl_available():
    """Returns (ok, message)."""
    if os.name != "nt":
        return True, "native-linux"
    try:
        p = subprocess.run(["wsl.exe", "--status"],
                           capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        return False, "WSL nei"
    if p.returncode != 0:
        return False, "WSL thikmoto boseni"
    return True, ""


def _wsl_path(win_path):
    drive = win_path[0].lower()
    rest = win_path[2:].replace("\\", "/")
    return "/mnt/%s%s" % (drive, rest)


def tool_linux_status():
    """Linux environment ready kina check."""
    if os.name != "nt":
        return "Tumi itimodhye Linux-e acho ✅"
    ok, msg = _wsl_available()
    if not ok:
        return "ERROR: %s — setup-linux.ps1 chalao" % msg
    p = subprocess.run(["wsl.exe", "--list", "--quiet"],
                       capture_output=True, text=True, timeout=15)
    distros = p.stdout.strip() or "(kono distro nei)"
    return "WSL ready ✅\nDistros:\n%s" % distros


def tool_linux_run(command, timeout=60):
    """Asol Linux (WSL2/Ubuntu)-te command chalano."""
    if os.name != "nt":
        return tool_run_shell(command, timeout=timeout)
    ok, msg = _wsl_available()
    if not ok:
        return "ERROR: %s — setup-linux.ps1 chalao" % msg
    wsl_path = _wsl_path(_ws())
    full = "cd '%s' && %s" % (wsl_path, command)
    try:
        proc = subprocess.run(["wsl.exe", "bash", "-lc", full],
                              capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
        return "[wsl exit %d]\n%s" % (proc.returncode, _clip(out))
    except subprocess.TimeoutExpired:
        return "ERROR: somoy sesh"


TOOLS.update({
    "linux_status": {"fn": tool_linux_status, "level": "green"},
    "linux_run":    {"fn": tool_linux_run,    "level": "red"},
})

TOOL_SCHEMAS.extend([
    {"type": "function", "function": {
        "name": "linux_status",
        "description": "Check if the inbuilt Linux (WSL2/Ubuntu) is ready.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "linux_run",
        "description": "Run a command inside the inbuilt Linux (WSL2/Ubuntu).",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "default": 60}},
            "required": ["command"]}}},
])
