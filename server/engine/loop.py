"""The agent loop: user message -> plan -> tools -> report.

Mirrors how Muse works: the brain decides, tools do the work,
and risky actions go through the approve callback first.
"""
import json
import os

from .brain import BrainError
from .tools import TOOLS, TOOL_SCHEMAS

SYSTEM_PROMPT = """You are a personal AI coding agent running on the user's own PC.
You speak Bengali (Bangla) by default, like a friendly senior developer brother.

How you work:
1. Understand the user's request (Bengali/English/Banglish all fine).
2. Make a short plan, then use tools step by step. All file work happens
   INSIDE the workspace folder — never outside it.
3. If the inbuilt Linux is ready (linux_status), prefer linux_run for
   Linux-native work — you are a Linux agent at heart.
4. When done, report in Bengali: what you did, what the result was,
   and the exact next step if something needs the user.
5. Token economy: finish in as few steps as possible. Write complete,
   correct files in one go; avoid tiny edits, repeated verification,
   and re-reading whole large files.

Hard rules (never break, even if the user asks):
- Never touch anything outside the workspace.
- Never help with: hacking others' accounts, stealing passwords, spam,
  harassment, fraud, impersonation, or weakening system security.
- If a request looks harmful, refuse briefly in Bengali and offer a
  legitimate alternative.
- Be honest about what you can't verify. Don't invent file contents or
  command outputs — use the tools to check.
"""

MAX_STEPS = 12

# এই ধাপ থেকে কাজ "ভারী" — router তখন Xkiro-কে আগে ডাকবে (Groq দিয়ে
# শুরু, গভীর ধাপে শক্তিশালী মডেল)। kamla.env-তে KAMLA_HEAVY_STEP বদলানো যায়।
try:
    HEAVY_STEP = int(os.environ.get("KAMLA_HEAVY_STEP", "3"))
except ValueError:
    HEAVY_STEP = 3

# Ethical deny-list: checked before any tool runs.
DENY_PATTERNS = [
    "password crack", "brute force", "ddos", "keylogger",
    "phishing", "steal cookies", "bypass login",
]


_KEEP_FULL = 6          # শেষের এতগুলো মেসেজ হুবহু থাকবে
_BIG_ARG_KEYS = ("content", "code", "text")


def _slim_history(messages):
    """Token saver: পুরনো ধাপগুলোর মোটা অংশ (ফাইলের পুরো কনটেন্ট,
    লম্বা টুল-আউটপুট) ছেঁটে পাঠাই — ইতিহাস বারবার রি-সেন্ডে টোকেন
    ফুলে ওঠা ঠেকায়। সাম্প্রতিক ধাপগুলো হুবহু থাকে, কাজের মান থাকে।"""
    if len(messages) <= _KEEP_FULL + 1:
        return messages
    cutoff = len(messages) - _KEEP_FULL
    out = []
    for i, m in enumerate(messages):
        if i == 0 or i >= cutoff:
            out.append(m)
            continue
        m = dict(m)
        c = m.get("content")
        if m.get("role") == "tool" and isinstance(c, str) and len(c) > 240:
            m["content"] = c[:240] + " …[পুরনো আউটপুট সংক্ষেপিত]"
        if m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                tc = dict(tc)
                fn = dict(tc.get("function") or {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                    for k in _BIG_ARG_KEYS:
                        v = args.get(k)
                        if isinstance(v, str) and len(v) > 200:
                            args[k] = "[%d chars — আগেই পাঠানো হয়েছে]" % len(v)
                    fn["arguments"] = json.dumps(args, ensure_ascii=False)
                except Exception:
                    pass
                tc["function"] = fn
                calls.append(tc)
            m["tool_calls"] = calls
        out.append(m)
    return out


class Agent:
    def __init__(self, brain, memory=None):
        self.brain = brain
        self.memory = memory
        self.yellow_approved = set()  # remembered yellow approvals

    def _denied(self, text):
        t = text.lower()
        return any(p in t for p in DENY_PATTERNS)

    def run(self, user_text, approve, notify=None, history=None):
        """approve(tool_name, level, args) -> bool. notify(text) optional
        step reporter. history = past [{role, content}] turns (multi-turn)."""
        if self._denied(user_text):
            return ("ভাই, এই কাজটা আমি করতে পারবো না — এটা নিরাপত্তা-বিরোধী। "
                    "বৈধ কোনো বিকল্প থাকলে বলো, সেটা করে দিচ্ছি।")

        self.turn_usage = {"prompt": 0, "completion": 0, "total": 0}
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if self.memory:
            mem = self.memory.recall()
            if mem:
                messages.append({"role": "system",
                                 "content": "User memory:\n" + mem})
        for h in (history or [])[-16:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"],
                                 "content": str(h["content"])[:4000]})
        messages.append({"role": "user", "content": user_text})

        for step in range(MAX_STEPS):
            try:
                msg = self.brain.chat(_slim_history(messages), TOOL_SCHEMAS,
                                      heavy=step >= HEAVY_STEP)
                u = getattr(self.brain, "last_usage", None)
                if u:
                    self.turn_usage["prompt"] += u.get("prompt_tokens") or 0
                    self.turn_usage["completion"] += u.get("completion_tokens") or 0
                    self.turn_usage["total"] += u.get("total_tokens") or 0
            except BrainError as e:
                return "ব্রেইনে সমস্যা: %s" % e
            messages.append(msg)

            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                return msg.get("content") or "(কিছু বললো না)"

            for call in tool_calls:
                name = call["function"]["name"]
                args = json.loads(call["function"].get("arguments") or "{}")
                if notify:
                    notify("🔧 %s  %s" % (name, str(args)[:140]))
                entry = TOOLS.get(name)
                if not entry:
                    result = "ERROR: unknown tool"
                else:
                    level = entry["level"]
                    ok = True
                    if level == "red":
                        ok = approve(name, level, args)  # asks EVERY time
                    elif level == "yellow" and name not in self.yellow_approved:
                        ok = approve(name, level, args)
                        if ok:
                            self.yellow_approved.add(name)
                    if not ok:
                        result = "USER DENIED this action."
                    else:
                        try:
                            result = str(entry["fn"](**args))
                        except Exception as e:
                            result = "ERROR: %s" % e
                if notify:
                    notify("📤 %s" % str(result)[:220])
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": result,
                })
        return "অনেকগুলো স্টেপ হয়ে গেলো — থামছি। সংক্ষেপে আবার বলো কী চাও।"
