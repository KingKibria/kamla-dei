# Kamla Dei LAN Host + Pairing Verification Evidence — 2026-11-14

Plan: `docs/superpowers/plans/2026-11-14-lan-host-and-verification.md`, Task 1 Step 3 (GREEN).
Method: Playwright (Chromium) black-box test against the UI + a live local engine.
Script: `lan-browser-check.py` (same directory).

## What was tested

The UI's "📱 ফোন থেকে PC-তে (LAN)" section: IP + port input, probe, pairing
via the custom address, address remembering, and the wrong-address path —
plus the pairing-endpoint bug found during testing (see below).

## Environment (honest limits)

- Engine: `server/app.py` v1.3.3, fresh DB, demo brain, `PORT=8790`,
  `KAMLA_NO_BROWSER=1`, run from a scratch copy in `/tmp` (staging dir untouched).
- UI under test: the exact file pushed to the `gh-pages` branch (byte-identical
  staging copy, served locally on `127.0.0.1:8901`), because this VM's egress
  proxy blocks Chromium from reaching the public Pages URL directly.
  The live deployment itself is confirmed at the git level (branch head
  advanced); a fresh public crawl may lag the push by minutes.
- LAN address simulated with `127.0.0.2` (a second loopback address): the VM's
  own `198.19.0.2` is unreachable from inside the sandbox, and a true
  `192.168.x.x` test needs a second device. The tested code path is identical
  (user-entered base URL → probe → pairing → status sync); only the address
  string differs. The real phone + PC test remains Hasan's step (blocked item B1).
- Loopback candidates (`127.0.0.1`/`localhost`) were blocked in the browser so
  the LAN path was tested in isolation.

## Results — ALL 5 CHECKS PASSED (2026-11-14, after the pairing fix)

| # | Check | Evidence |
|---|---|---|
| 1 | LAN section present on the page | IP input (placeholder `192.168.1.5`) + port input (default `8790`) + "LAN Engine খোঁজো" button found |
| 2 | Probe fires at the entered address | Requests observed: `health=2`, `pair/request=1` to `http://127.0.0.2:8790` |
| 3 | Pairing + approval + status sync end-to-end | Code-matched approve (as the PC screen would) → `status sync requests=2`, status line `LINK · CONNECTED`, `22 tools linked`, activity log `pairing approved on PC — token received` |
| 4 | Address remembered, no token persisted | After reload: IP input = `127.0.0.2`, `localStorage` keys = `['kd_lan_url']` only |
| 5 | Wrong address stays honestly OFFLINE | Only `/api/health` went to `:9999`; error shown: "কোনো Engine পাওয়া যায়নি…"; badge `OFFLINE · PRIVATE`; no CONNECTED state |

## Pairing-endpoint bug found and fixed during this test

- **Found:** the UI called `POST /api/bridge/pair` to start pairing. The engine
  has no such route and answered `401 {"error": "লগইন লাগবে"}`, so the UI
  wrongly concluded "এই Engine অটো-পেয়ারিং দেয়নি" and fell back to KD-key login.
  Proof: `POST /api/bridge/pair` → 401; `POST /api/bridge/pair/request` → 200
  with `{pair_id, code, expires_in: 120}`.
- **Scope:** not LAN-specific — the main one-click pairing flow was broken the
  same way. UI↔engine pairing had never been live-verified before (2026-10-23
  sandbox lockdown), so the bug likely existed since pairing was added (v1.3.3).
- **Fix:** UI artifact edit — pairing now uses `POST /api/bridge/pair/request`
  (no auth header on the public call) + `GET /api/bridge/pair/status?pair_id=`
  polling; no bare `/api/bridge/pair` call remains. No engine change.
- **Re-verified:** checks 2–3 above pass only with the fix (before the fix:
  `pair/request=0` and the UI asked for a key).

## Test-script bugs fixed along the way (not app bugs)

- `urllib` routed engine calls through the VM egress proxy → timeouts; fixed
  with a no-proxy opener in the script.
- Approving `pending[0]` could approve a stale pairing; fixed by matching the
  6-digit code shown in the UI to the pending list.
- A Playwright route pattern with a single trailing `*` cannot cross `/`, so
  loopback probes were not actually blocked at first; fixed with `**`.
- Asserting "OFFLINE absent from page text" is wrong: static help copy mentions
  OFFLINE. Assertions now use the status line (`LINK · CONNECTED` /
  `OFFLINE · PRIVATE`) and observed network requests.
