"""Tiny long-term memory: the agent remembers user facts across chats."""
import json
import os

MEM_FILE = os.path.expanduser("~/.agent-memory.json")


class Memory:
    def __init__(self, path=MEM_FILE):
        self.path = path
        self.data = {}
        if os.path.exists(path):
            try:
                with open(path) as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}

    def remember(self, key, value):
        self.data[key] = value
        self._save()

    def recall(self):
        if not self.data:
            return ""
        return "\n".join("- %s: %s" % (k, v) for k, v in self.data.items())

    def _save(self):
        try:
            with open(self.path, "w") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
