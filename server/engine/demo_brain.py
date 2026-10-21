"""Demo brain — scripted, no API key needed.

Lets the user SEE the full agent loop (plan -> tools -> approval -> report)
on first run, before they set up a real LLM key.
"""
import json


class DemoBrain:
    def __init__(self):
        self.step = 0

    def _tc(self, cid, name, args):
        return {"id": cid, "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)}}

    def chat(self, messages, tools, heavy=False):
        self.step += 1
        if self.step == 1:
            return {"role": "assistant", "content": None, "tool_calls": [
                self._tc("d1", "write_file", {
                    "path": "hello.py",
                    "content": "print('ডেমো: এজেন্ট কাজ করছে!')"})]}
        if self.step == 2:
            return {"role": "assistant", "content": None, "tool_calls": [
                self._tc("d2", "run_shell", {"command": "python hello.py"})]}
        if self.step == 3:
            return {"role": "assistant", "content": None, "tool_calls": [
                self._tc("d3", "search_files", {"pattern": "hello"})]}
        return {"role": "assistant",
                "content": ("ডেমো শেষ ✅\n\nআমি যা করলাম:\n"
                            "1. hello.py ফাইল বানালাম (তোমার অনুমতি নিয়ে)\n"
                            "2. shell-এ চালিয়ে দেখালাম (আবার অনুমতি নিয়ে)\n"
                            "3. search_files দিয়ে 'hello' লেখাটা খুঁজে দেখালাম\n\n"
                            "সব মিলিয়ে এখন ২২টা টুল আছে! আসল বুদ্ধি (API key) বসালে\n"
                            "যেকোনো কাজ এভাবেই করবো!")}
