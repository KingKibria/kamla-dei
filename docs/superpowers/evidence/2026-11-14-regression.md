# Kamla Dei Engine Regression Evidence — 2026-11-14

Plan: `docs/superpowers/plans/2026-11-14-lan-host-and-verification.md`, Task 2.
Role: স্বাধীন reviewer — কোডে কোনো বদল করা হয়নি, কিছু push করা হয়নি।

## পরিবেশ

- Engine: `server/app.py`, version 1.3.3, Python 3.12.3, stdlib only
- Run: `PORT=8791 KAMLA_NO_BROWSER=1 python3 server/app.py` (background, 8790 এড়িয়ে — Task 1-এর কাজের সাথে ধাক্কা নয়)
- DB: engine নিজে fresh SQLite বানিয়েছে (`data/kamla.db`, run-এর আগে `data/` ছিল না); key তৈরি + redeem engine-এর নিজের API দিয়ে — DB হাতে এডিট করা হয়নি
- Brain: demo (কোনো API key env নেই) — approval gate-ই যাচাইয়ের বিষয়
- Run শেষে server বন্ধ + `data/` ডিরেক্টরি মুছে ফেলা হয়েছে (staging dir পরিষ্কার)
- Token/key-এর মান এই ফাইলে নেই — শুধু দৈর্ঘ্য/আংশিক রূপ; admin password লেখা হয়নি (engine প্রথম boot-এ নিজেই ছাপে)

## ফলাফল সারাংশ

| Step | ফলাফল |
|---|---|
| 1. Boot + health | PASS |
| 2. Status + bridge auth (401/403/200) | PASS |
| 3. Pairing পূর্ণ চক্র (token ঠিক একবার) | PASS |
| 4. Approval-সহ চ্যাট (bridge token) | PASS |
| 5. PNA preflight | PASS |

---

## Step 1: Engine boot + health — PASS

Command:

```sh
PORT=8791 KAMLA_NO_BROWSER=1 python3 server/app.py   # background
curl -s -m 5 -w "\nHTTP:%{http_code} EXIT:%{exitcode}\n" http://127.0.0.1:8791/api/health
```

Output (exit 0):

```json
{"ok": true, "app": "Kamla Dei Engine", "version": "1.3.3"}
HTTP:200 EXIT:0
```

নোট: plan-এ লেখা `{"ok": true, "version": "1.3.3"}`-এর সাথে একটি বাড়তি `"app"` ফিল্ড আছে — version ঠিক 1.3.3, ok true। এটা fail নয়।

## Step 2: Status + bridge auth — PASS

Commands (B = `http://127.0.0.1:8791`):

```sh
curl -s -w "\nHTTP:%{http_code}\n" $B/api/status
curl -s -X POST $B/api/bridge/auth -H 'Content-Type: application/json' \
  -d '{"key":"KD-AAAA-BBBB-CCCC"}'
# admin login (engine-এর প্রথম boot-এ ছাপানো default credential) -> POST /api/admin/keys
#   {plan: pro, days: 30, count: 1} -> test key KD-2SS6-…-7823
curl -s -X POST $B/api/bridge/auth -d '{"key":"<unredeemed test key>"}'
# POST /api/register (test user) -> POST /api/redeem {code} -> 200, plan pro
curl -s -X POST $B/api/bridge/auth -d '{"key":"<redeemed test key>"}'
curl -s $B/api/status -H "Authorization: Bearer <bridge token>"
curl -s $B/api/status -H "X-Kamla-Key: <redeemed test key>"   # bonus
```

Outputs (সব curl exit 0):

| চেক | HTTP | Body (সংক্ষেপ) |
|---|---|---|
| (a) token ছাড়া `/api/status` | 401 | `{"ok": false, "error": "key rejected"}` |
| (b) ভুল KD- key-এ `/api/bridge/auth` | 401 | `{"ok": false, "error": "key-টা সঠিক না"}` |
| (c) redeem-না-করা key-এ `/api/bridge/auth` | 403 | `{"ok": false, "error": "এই key এখনো কোনো অ্যাকাউন্টে চালু হয়নি — …"}` |
| redeem (`/api/redeem`) | 200 | `{"ok": true, "plan": "pro", "expires_at": "2026-12-14T10:01:40+00:00"}` |
| (d) redeem-করা key-এ `/api/bridge/auth` | 200 | `ok: true, name: Regression Tester, plan: pro, version: 1.3.3, token len: 77` |
| (d) bridge token-এ `/api/status` | 200 | `ok: true, version: 1.3.3, tools: 22, tool_count: 22, brain: demo, brain_chain: demo, plan: pro, user: Regression Tester` |
| bonus: `X-Kamla-Key` হেডারে `/api/status` | 200 | একই status body (tools: 22, brain: demo) |

টুল গণনা: `tools` = 22 এবং `tool_count` = 22 — দুটো ফিল্ডেই; `brain` ও `brain_chain` ফিল্ড আছে (মান `demo`, কোনো API key নেই বলে)।

## Step 3: Pairing পূর্ণ চক্র — PASS

Commands:

```sh
curl -s -X POST $B/api/bridge/pair/request -H 'Content-Type: application/json' -d '{}'
curl -s $B/api/bridge/pair/pending -H "Authorization: Bearer <login token>"
curl -s -X POST $B/api/bridge/pair/approve -H "Authorization: Bearer <login token>" \
  -d '{"pair_id":"<pair_id>","ok":true}'
curl -s "$B/api/bridge/pair/status?pair_id=<pair_id>"   # ১ম বার
curl -s "$B/api/bridge/pair/status?pair_id=<pair_id>"   # ২য় বার
curl -s $B/api/status -H "Authorization: Bearer <pairing token>"  # bonus
```

Outputs (সব curl exit 0):

| ধাপ | HTTP | Body (সংক্ষেপ) |
|---|---|---|
| pair/request | 200 | `{"ok": true, "pair_id": "dea159c1", "code": "974889", "expires_in": 120}` |
| pair/pending | 200 | `{"pending": [{"pair_id": "dea159c1", "code": "974889"}]}` |
| pair/approve ok:true | 200 | `{"ok": true}` |
| pair/status (১ম) | 200 | `ok: true, status: approved, name: Regression Tester, plan: pro, version: 1.3.3, token len: 77` |
| pair/status (২য়) | 404 | `{"ok": false, "status": "unknown"}` — token নেই |
| bonus: pairing token-এ `/api/status` | 200 | `ok: true, tools: 22, brain: demo, plan: pro` |

নোট: plan-এ ২য় status কলের জন্য "410/gone" লেখা ছিল; আসল আচরণ 404 `{"ok": false, "status": "unknown"}`। মূল শর্ত — token ঠিক একবারই মেলে — পূরণ হয়েছে; status code-এর এই পার্থক্য bug নয়, plan-এর wording-এর সাথে অমিল মাত্র।

## Step 4: Approval-সহ চ্যাট (bridge token) — PASS

Demo brain-এর scripted ফ্লো: write_file (yellow) → run_shell (red) → search_files (green) → "ডেমো শেষ ✅"। তাই দুটো আলাদা approval লাগে — দুটো gate-ই আলাদাভাবে যাচাই করা হয়েছে।

Commands (Python urllib, bridge token-এ):

```text
POST /api/chats -> {"id": 1}                                    HTTP 200
POST /api/chats/1/send {"text": "hello.py বানিয়ে চালাও"}       HTTP 200
GET  /api/chats/1/poll?since=0  (approval না আসা পর্যন্ত)        HTTP 200
POST /api/chats/1/approve {"ok": true}                          HTTP 200
GET  /api/chats/1/poll?since=0  (২য় approval না আসা পর্যন্ত)    HTTP 200
POST /api/chats/1/approve {"ok": true}                          HTTP 200
GET  /api/chats/1/poll?since=0  (busy:false না হওয়া পর্যন্ত)    HTTP 200
GET  /api/files                                                 HTTP 200
```

মূল প্রমাণ:

- ১ম approval (pending অবস্থায়): `⚠️ এজেন্ট করতে চায়: write_file (yellow) {'path': 'hello.py', ...}`, poll-এ `busy: true`
- **approval-এর আগে `hello.py` ডিস্কে ছিল না** — `hello.py paths on disk: NONE (correct)` (workspace: `data/users/2/workspace/`)
- approve #1-এর পর: tool মেসেজ `📤 OK: 31 chars written to hello.py`; ফাইল ডিস্কে তৈরি
- ২য় approval (pending অবস্থায়): `⚠️ এজেন্ট করতে চায়: run_shell (red) {'command': 'python hello.py'}` — এই অবস্থায় poll-এর কোনো মেসেজে run_shell-এর `[exit …]` আউটপুট ছিল না (`run_shell output present BEFORE 2nd approval? False`) — অর্থাৎ red ধাপ approval ছাড়া চলেনি
- approve #2-এর পর: `📤 [exit 0] ডেমো: এজেন্ট কাজ করছে!` (`python` → `python3` fix কাজ করেছে), তারপর green `search_files` approval ছাড়াই চলেছে
- শেষ poll: `busy: false`, `approval: None`, `used: 1`; agent মেসেজ `ডেমো শেষ ✅ … সব মিলিয়ে এখন ২২টা টুল আছে!`
- ডিস্কে ফাইল: `data/users/2/workspace/hello.py` → `print('ডেমো: এজেন্ট কাজ করছে!')`
- `/api/files`: `{"files": [{"path": "hello.py", "size": 65}]}`

Script exit code: 0।

## Step 5: PNA preflight — PASS

Command:

```sh
curl -s -i -X OPTIONS http://127.0.0.1:8791/api/health \
  -H "Origin: https://kingkibria.github.io" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Private-Network: true"
```

Output (exit 0):

```http
HTTP/1.0 204 No Content
Server: BaseHTTP/0.6 Python/3.12.3
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, OPTIONS
Access-Control-Allow-Headers: Authorization, Content-Type
Access-Control-Allow-Private-Network: true
Content-Length: 0
```

Bonus — সাধারণ GET `/api/health`-এর response-এও একই দুটো হেডার আছে:

```http
HTTP/1.0 200 OK
Access-Control-Allow-Origin: *
Access-Control-Allow-Private-Network: true
```

## সিদ্ধান্ত

Engine v1.3.3-এর API surface (health, status, bridge auth, pairing, approval-সহ চ্যাট, PNA) — সব চেক পাস। কোনো bug পাওয়া যায়নি। Plan-এর wording-এর সাথে দুটো ছোট অমিল নোট করা হয়েছে (Step 1-এর বাড়তি `app` ফিল্ড, Step 3-এর ২য় status কলে 404 বনাম 410) — দুটোই আচরণগত ঘাটতি নয়।
