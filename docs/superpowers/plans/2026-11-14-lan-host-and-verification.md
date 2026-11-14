# Kamla Dei Completion (LAN Host + Verification) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kamla Dei-র বাকি কাজের মধ্যে যা Hasan-এর PC/সিদ্ধান্ত ছাড়া করা যায়, তা Superpowers পদ্ধতিতে শেষ করা — LAN host অপশন + নতুন প্রমাণসহ পূর্ণ regression যাচাই।

**Architecture:** Engine-এ কোনো বদল নয় (LAN-প্রস্তুত যাচাইকৃত)। শুধু UI artifact-এ LAN ঠিকানা ইনপুট + probe যোগ; engine-এর পুরো API সারফেস নতুন করে E2E যাচাই; spec/plan repo-তে সংরক্ষণ; UI re-export + gh-pages push।

**Tech Stack:** Python 3 stdlib engine (ThreadingHTTPServer, port 8790, 0.0.0.0); UI = single-file static artifact (vanilla JS); GitHub push-files checkpoint (এই workspace-এ git commit-এর বদলে push-files-ই checkpoint — Ruling 1 দেখো)।

**Spec:** `docs/superpowers/specs/2026-11-14-completion-scope.md`

## Global Constraints

- Engine কোডে কোনো বদল নয়, যদি না regression-এ বাগ ধরা পড়ে (তখন আলাদা task + TDD)।
- UI-তে কোনো ভুয়া CONNECTED নয় — OFFLINE সৎভাবে দেখাতে হবে (আগের নিয়ম বহাল)।
- কোনো secret/key চ্যাটে, কোডে, বা repo-তে নয় — কখনোই না।
- Kamla Dei-র জন্য চ্যাটে কোনো zip/file ডেলিভারি নয় — ডেলিভারি শুধু UI artifact + GitHub।
- কোনো completion দাবি verification-before-completion ছাড়া নয় — fresh command output, exit code, failure count পড়ে তবেই দাবি।
- LAN probe-এ http (https নয়) — LAN ঠিকানা `http://<ip>:8790` আকারে; port ডিফল্ট 8790, বদলানো যাবে।
- Pairing token/session token শুধু tab memory-তে — localStorage-এ শুধু LAN ঠিকানাটা মনে রাখা যাবে, token নয়।

## Review Focus

- LAN ঠিকানায় ভুল IP/port দিলে UI সৎভাবে "পাওয়া যায়নি" দেখায়, ভুয়া CONNECTED নয় — Task 1-এর টেস্টে আছে।
- ফোনের ব্রাউজার থেকে HTTPS Pages UI → http LAN fetch: PNA preflight engine-এ যাচাইকৃত হতে হবে — Task 2-এর টেস্টে আছে।
- LAN ঠিকানা মনে রাখা হলেও token কখনো persist হয় না — Task 1-এর টেস্টে আছে।
- Loopback (127.0.0.1/localhost) auto-discover আগের মতোই কাজ করে — LAN যোগ করলে ভাঙে না — Task 1-এর টেস্টে আছে।
- Engine port busy থাকলে পরের port নেয় — LAN probe-এ port বদলানোর সুযোগ থাকে — Task 1-এ ইনপুটে port অন্তর্ভুক্ত।

---

### Task 1: UI — LAN host অপশন (ফোন থেকে PC-তে Connect)

**Files:**
- Modify: artifact `kamla-dei-ui-design` (bridge/connect প্যানেল — LAN ঠিকানা ইনপুট + probe + মনে রাখা)
- Test: Playwright browser test, local engine-এর বিরুদ্ধে (VM IP = LAN ঠিকানার অনুকরণ)

**Interfaces:**
- Consumes: engine `GET /api/health` (probe), `POST /api/bridge/pair/request`, `GET /api/bridge/pair/status?pair_id=`, `GET /api/status` (Bearer) — সব আগের মতো, শুধু base URL বদলায়।
- Produces: `window`/UI state-এ `lanBaseUrl` (string, যেমন `http://192.168.1.5:8790`); localStorage key `kd_lan_url` (ঠিকানা মাত্র, token নয়)।

- [ ] **Step 1: RED — বর্তমান UI-তে LAN অপশন নেই, প্রমাণ করো**

Run: `grep -ri "lan\|192.168\|ল্যান" ~/workspace/kamla-dei-pages/index.html | head`
Expected: LAN ইনপুট/probe-সংক্রান্ত কোনো match নেই (শুধু অপ্রাসঙ্গিক শব্দ থাকতে পারে)।

- [ ] **Step 2: artifact.edit দিয়ে LAN অপশন যোগ করো**

Bridge প্যানেলে (ONE-CLICK CONNECT-এর নিচে, STEP 2-এর ওপরে): "📱 ফোন থেকে PC-তে (LAN)" সেকশন — IP/host ইনপুট (placeholder `192.168.1.5`), port ইনপুট (ডিফল্ট `8790`), "LAN Engine খোঁজো" বোতাম। বোতাম চাপলে `http://<ip>:<port>/api/health` probe; পেলে pairing ফ্লো আগের মতো (PC-র স্ক্রিনে Allow); না পেলে সৎ error বার্তা + OFFLINE থাকে। সফল ঠিকানা `kd_lan_url`-এ সেভ; পেজ খুললে সেভ করা ঠিকানা ইনপুটে বসে (auto-probe নয় — loopback auto-discover আগের মতোই চলে)। Loopback ফ্লোতে কোনো বদল নয়। ডিজাইন আগের HUD স্টাইলের সাথে মেলে।

- [ ] **Step 3: GREEN — browser test: LAN ঠিকানায় probe + pairing-wait**

Run: Playwright — local engine চালু (PORT=8790, 0.0.0.0) + exported UI serve করে: (a) VM-র IP বসিয়ে "LAN Engine খোঁজো" → pairing-wait state আসে; (b) ভুল IP (`192.0.2.1`) → সৎ error, OFFLINE থাকে; (c) reload-এর পর ইনপুটে ঠিকানা মনে থাকে, token localStorage-এ নেই।
Expected: (a) pairing-wait দেখায়, (b) error + OFFLINE, (c) ঠিকানা মনে থাকে + `kd_lan_url` ছাড়া কোনো token key নেই।

- [ ] **Step 4: Checkpoint**

`artifact.export` → `~/workspace/kamla-dei-pages/index.html` বদলাও → `github push-files` (gh-pages branch)। Pages লাইভ যাচাই: `browser.open https://kingkibria.github.io/kamla-dei/` — LAN সেকশনের লেখা দেখা যায়।

### Task 2: Engine regression E2E — নতুন প্রমাণসহ

**Files:**
- Modify: কিছু নয় (শুধু যাচাই; বাগ পেলে আলাদা task)।
- Test: shell + curl স্ক্রিপ্ট, engine আলাদা port-এ (PORT=8791 — Task 1-এর engine-এর সাথে ধাক্কা নয়)।

**Interfaces:**
- Consumes: `server/app.py` (v1.3.3), `server/engine/*`, `web/*` (pairing banner)।
- Produces: এই plan-এর ledger-এ test evidence (প্রতিটা চেকের command + output + exit code)।

- [ ] **Step 1: Engine boot + health**

Run: `PORT=8791 KAMLA_NO_BROWSER=1 python3 server/app.py` (background) → `curl -s http://127.0.0.1:8791/api/health`
Expected: `{"ok": true, "version": "1.3.3"}` (exact version), exit 0।

- [ ] **Step 2: Status + bridge auth (200/401/403)**

Run: `curl` দিয়ে — (a) token ছাড়া `/api/status` → 401; (b) ভুল KD- key দিয়ে `/api/bridge/auth` → 401; (c) redeem-না-করা key দিয়ে → 403; (d) DB-তে redeem-করা key দিয়ে → 200 + token, সেই token-এ `/api/status` → 200, ২২ টুল + brain ফিল্ড।
Expected: ঠিক এই status code-গুলো, কোনো ব্যতিক্রম নয়।

- [ ] **Step 3: Pairing সম্পূর্ণ চক্র**

Run: `POST /api/bridge/pair/request` → `{pair_id, code, expires_in:120}`; `GET /api/bridge/pair/pending` (login token-এ) → তালিকায় code; `POST /api/bridge/pair/approve {pair_id, ok:true}` → token; `GET /api/bridge/pair/status?pair_id=` → token ঠিক একবার; দ্বিতীয়বার → token নেই (410/gone)।
Expected: প্রতিটা ধাপের response ঠিক spec-মতো; token দ্বিতীয়বার মেলে না।

- [ ] **Step 4: Approval-সহ চ্যাট (bridge token-এ)**

Run: bridge token-এ `POST /api/chats` → `POST /api/chats/{id}/send` (write_file + run_shell চায় এমন task) → `GET /api/chats/{id}/poll?since=` → approval আসে → `POST /api/chats/{id}/approve` → কাজ শেষ, ফাইল তৈরি, বাংলা রিপোর্ট।
Expected: approval ছাড়া RISK ধাপ চলে না; approve-এর পর ফাইল ডিস্কে থাকে; poll-এ `busy:false` হয়।

- [ ] **Step 5: PNA preflight (LAN পথের প্রমাণ)**

Run: `curl -s -i -X OPTIONS http://127.0.0.1:8791/api/health -H "Origin: https://kingkibria.github.io" -H "Access-Control-Request-Method: GET" -H "Access-Control-Request-Private-Network: true"`
Expected: 204 + `Access-Control-Allow-Private-Network: true` + `Access-Control-Allow-Origin: *`।

- [ ] **Step 6: Ledger-এ evidence লেখো**

প্রতিটা step-এর command, exit code, ও মূল output `docs/superpowers/evidence/2026-11-14-regression.md`-এ লেখো। কোনো step fail হলে সেটা fail-ই লেখো — লুকানো নয়।

### Task 3: Docs + repo checkpoint

**Files:**
- Create: `docs/superpowers/specs/2026-11-14-completion-scope.md` (আগেই লেখা), `docs/superpowers/plans/2026-11-14-lan-host-and-verification.md` (এই plan), `docs/superpowers/evidence/2026-11-14-regression.md` (Task 2-এর evidence)।
- Modify: `~/workspace/goals/ai-pc-android/GOAL.md` — build progress-এ এই কাজের এন্ট্রি।

- [ ] **Step 1: Evidence ফাইল যাচাই করো** — Task 2-এর সব step-এর evidence আছে, কোনো দাবি প্রমাণ ছাড়া নেই।
- [ ] **Step 2: `github push-files` দিয়ে main branch-এ docs পাঠাও** (engine/web অপরিবর্তিত — শুধু docs/)। Push-এর commit SHA রিপোর্টে লেখো।
- [ ] **Step 3: Final review** — plan-এর প্রতিটা task-এর বিরুদ্ধে চেকলিস্ট: Task 1 (LAN UI live), Task 2 (সব evidence), Task 3 (docs pushed)। ঘাটতি থাকলে রিপোর্টে সৎভাবে লেখো — "সম্পূর্ণ" দাবি নয়।

## Blocked (এই plan-এর বাইরে — Hasan-এর কাজ)

- **B1:** প্রথম লাইভ PC connect টেস্ট — ধাপ: Pages UI খুলে STEP 2 Launcher নামাও → .bat চালাও → ONE-CLICK CONNECT → PC-র স্ক্রিনে Allow → স্ক্রিনশট পাঠাও। এটা ছাড়া Kamla Dei "সম্পূর্ণ" নয়।
- **B2:** আসল Groq key দিয়ে success-path টেস্ট + টোকেন রিপোর্ট (তার key, তার PC)।
- **B3:** Pricing সিদ্ধান্ত + bKash/manual payment ফ্লো (তার সিদ্ধান্ত লাগবে)।
- **B4:** Beta + public launch (B1–B3-এর পর, তার সম্মতিতে)।

## Rulings

- **Ruling 1:** এই workspace-এ git repo নেই (push-files checkpoint) — plan-এর "commit" ধাপ = `github push-files` + commit SHA রেকর্ড। ভুল হলে খরচ: checkpoint ইতিহাস git-এর মতো নয়, কিন্তু repo-ই checkpoint (GOAL.md-এর নিয়ম)।
- **Ruling 2:** Execution method = inline (executing-plans), subagent-driven নয় — task মাত্র ৩টা, পরস্পর-নির্ভর, আর UI কাজ artifact builder-এই হয়। তবে Task 2-এর regression একজন স্বাধীন subagent চালাবে, যাতে evidence দ্বিতীয় চোখে যাচাই হয়।
- **Ruling 3:** Brainstorming-এর প্রশ্ন-পর্ব বাদ — scope আগেই Hasan-এর সিদ্ধান্তে ঠিক আছে (GOAL.md + blueprint v2); নতুন design সিদ্ধান্ত নেই, শুধু বাকি ধাপ শেষ করা।
- **Ruling 4 (2026-11-14, Task 1 Step 3 GREEN টেস্টে ধরা পড়া বাগ):** UI pairing শুরু করতে `POST /api/bridge/pair` ডাকত — Engine-এর আসল endpoint `POST /api/bridge/pair/request`। ভুল পথে Engine 401 দেয়, UI ভুল করে "অটো-পেয়ারিং দেয়নি" বলে KD-key fallback-এ যায়। প্রমাণ: curl-এ `/api/bridge/pair` → 401 `{"error": "লগইন লাগবে"}`, `/api/bridge/pair/request` → 200 + pair_id/code। এটা LAN-নির্দিষ্ট নয় — মূল one-click pairing ফ্লোও একইভাবে ভাঙা (UI↔engine pairing আগে কখনো লাইভ যাচাই হয়নি — 2026-10-23-এ sandbox lockdown-এ হয়নি)। ফিক্স: UI artifact-এ endpoint ঠিক করা (artifact.edit dispatched 2026-11-14); ফিক্সের পর GREEN টেস্ট আবার চালিয়ে তবেই Task 1 সম্পূর্ণ বলা যাবে। Engine-এ কোনো বদল নয় — Engine-ই spec।
