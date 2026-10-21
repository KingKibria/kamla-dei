"""LLM brain — OpenAI-compatible chat completions with function calling.

Multi-provider with KEY POOLS (v1.3.0). Design (Hasan's plan):
  * Normal work runs on Groq (fast). Heavy steps escalate to Xkiro.
  * Each provider can hold MANY keys. When a key hits its limit (429)
    or is rejected (401/403) it goes into cooldown and the pool moves
    to the next key — work continues without the user noticing.
  * If a whole provider pool is exhausted, the other provider answers.
  * If nothing is configured, the caller falls back to the demo brain.

Configure in kamla.env (the user sets keys themselves, never in chat):
    GROQ_API_KEYS     comma-separated Groq keys (pool)
    GROQ_API_KEY      single Groq key (pool of 1) — either form works
    GROQ_MODEL        default: openai/gpt-oss-120b
    KAMLA_API_KEYS    comma-separated Xkiro keys (pool)
    KAMLA_API_KEY     single Xkiro key — either form works
    KAMLA_MODEL       default: qwen/qwen3.8-max:free
    KAMLA_HEAVY_STEP  agent step from which work counts as heavy (default 3)
    AGENT_API_BASE / AGENT_API_KEY / AGENT_MODEL  (legacy aliases)

Note: a provider's quota may be per-account rather than per-key —
the pool simply rotates through whatever keys it is given.
"""
import json
import os
import time
import urllib.request
import urllib.error


class BrainError(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


_CHROME_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")  # Cloudflare 1010 fix

GROQ_BASE = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
XKIRO_BASE = "https://api.xkiro.com/v1"
XKIRO_DEFAULT_MODEL = "qwen/qwen3.8-max:free"

COOLDOWN_RATE = 90        # 429: key rests ~90s (per-minute limits)
COOLDOWN_AUTH = 3600      # 401/403: key rests 1h (dead key / no balance)


def _split_keys(*values):
    out = []
    for v in values:
        for part in (v or "").split(","):
            k = part.strip()
            if k and k not in out:
                out.append(k)
    return out


class Brain:
    """One provider endpoint with one key."""

    def __init__(self, base_url=None, api_key=None, model=None,
                 timeout=120, name="xkiro"):
        self.name = name
        self.base_url = (base_url or os.environ.get("KAMLA_API_BASE")
                         or os.environ.get("AGENT_API_BASE")
                         or XKIRO_BASE).rstrip("/")
        self.api_key = api_key or ""
        self.model = model or XKIRO_DEFAULT_MODEL
        self.timeout = timeout
        self.last_usage = None
        try:
            self.max_tokens = int(os.environ.get("KAMLA_MAX_TOKENS", "2500"))
        except ValueError:
            self.max_tokens = 2500

    def configured(self):
        return bool(self.base_url and self.api_key)

    def chat(self, messages, tools):
        """One brain turn. Returns the assistant message dict."""
        if not self.configured():
            raise BrainError("Brain not configured.")
        payload = {"model": self.model, "messages": messages,
                   "tools": tools, "max_tokens": self.max_tokens}
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
                "User-Agent": _CHROME_UA,
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            raise BrainError("Brain API error %s: %s" % (e.code, body),
                             status=e.code)
        except Exception as e:
            raise BrainError("Brain request failed: %s" % e)
        self.last_usage = data.get("usage") or None
        return data["choices"][0]["message"]


class PooledBrain:
    """One provider (base URL + model) with a rotating pool of keys."""

    def __init__(self, name, base_url, model, keys):
        self.name = name
        self.base_url = base_url
        self.model = model
        self.keys = list(keys)
        self._cool = {}          # key index -> cooldown-until timestamp
        self._next = 0           # round-robin pointer
        self.last_usage = None
        self.last_key_no = None  # 1-based, for display only — never the key

    def configured(self):
        return bool(self.keys)

    def _available(self):
        now = time.time()
        return [i for i in range(len(self.keys))
                if self._cool.get(i, 0) <= now]

    def chat(self, messages, tools):
        if not self.keys:
            raise BrainError("%s: no keys configured" % self.name)
        avail = self._available()
        if not avail:
            raise BrainError("%s: সব key এখন cooldown-এ" % self.name)
        # round-robin starting point, restricted to available keys
        start = self._next % len(avail)
        last_err = None
        for off in range(len(avail)):
            idx = avail[(start + off) % len(avail)]
            brain = Brain(base_url=self.base_url,
                          api_key=self.keys[idx], model=self.model,
                          name=self.name)
            try:
                msg = brain.chat(messages, tools)
            except BrainError as e:
                last_err = e
                if e.status == 429:
                    self._cool[idx] = time.time() + COOLDOWN_RATE
                elif e.status in (401, 403):
                    self._cool[idx] = time.time() + COOLDOWN_AUTH
                continue
            self._next = (avail.index(idx) + 1) % len(avail)
            self.last_usage = brain.last_usage
            self.last_key_no = idx + 1
            return msg
        raise BrainError("%s: পুলের সব key ব্যর্থ — %s"
                         % (self.name, last_err))


def make_providers():
    """Build {name: PooledBrain} from the environment."""
    providers = {}
    groq_keys = _split_keys(os.environ.get("GROQ_API_KEYS"),
                            os.environ.get("GROQ_API_KEY"))
    groq_keys = [k for k in groq_keys if not k.startswith("gsk_xxxx")]
    if groq_keys:
        providers["groq"] = PooledBrain(
            "groq", GROQ_BASE,
            os.environ.get("GROQ_MODEL") or GROQ_DEFAULT_MODEL, groq_keys)
    xkiro_keys = _split_keys(os.environ.get("KAMLA_API_KEYS"),
                             os.environ.get("KAMLA_API_KEY"),
                             os.environ.get("AGENT_API_KEY"))
    xkiro_keys = [k for k in xkiro_keys if not k.startswith("sk-xxxx")]
    if xkiro_keys:
        base = (os.environ.get("KAMLA_API_BASE")
                or os.environ.get("AGENT_API_BASE") or XKIRO_BASE)
        model = (os.environ.get("KAMLA_MODEL")
                 or os.environ.get("AGENT_MODEL") or XKIRO_DEFAULT_MODEL)
        providers["xkiro"] = PooledBrain("xkiro", base, model, xkiro_keys)
    return providers


class RouterBrain:
    """Routes by task weight, rotates key pools, falls back across
    providers. heavy=False → Groq first; heavy=True → Xkiro first."""

    def __init__(self, providers=None):
        self.providers = providers if providers is not None \
            else make_providers()
        self.last_usage = None
        self.last_provider = None
        self.last_model = None
        self.last_key_no = None

    def configured(self):
        return bool(self.providers)

    def describe(self):
        p = self.providers.get("groq") or self.providers.get("xkiro")
        if not p:
            return "demo"
        return "%s · %s (%d key)" % (p.name, p.model, len(p.keys))

    def chain(self):
        return " → ".join("%s/%s ×%d key" % (p.name, p.model, len(p.keys))
                          for p in self.providers.values()) or "demo"

    def chat(self, messages, tools, heavy=False):
        if not self.providers:
            raise BrainError("Brain not configured.")
        order = ["xkiro", "groq"] if heavy else ["groq", "xkiro"]
        last_err = None
        for name in order:
            p = self.providers.get(name)
            if not p:
                continue
            try:
                msg = p.chat(messages, tools)
            except BrainError as e:
                last_err = e
                continue
            self.last_usage = p.last_usage
            self.last_provider = p.name
            self.last_model = p.model
            self.last_key_no = p.last_key_no
            return msg
        raise BrainError("সব brain provider ব্যর্থ — শেষ ত্রুটি: %s"
                         % last_err)
