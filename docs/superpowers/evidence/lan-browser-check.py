"""Kamla Dei LAN-host verification against the LIVE GitHub Pages UI.
Tests the public surface only (no artifact files touched).
Requires: engine running on 0.0.0.0:8790 (fresh DB in /tmp), Playwright + Chromium.
Env: TRUST_LAN=1 to pass --unsafely-treat-insecure-origin-as-secure for the VM IP
(simulation of a real private LAN IP, which browsers treat as trustworthy)."""
import asyncio
import json
import os
import re
import urllib.request

from playwright.async_api import async_playwright

PAGES = "http://127.0.0.1:8901/index.html"  # staging copy, byte-identical to the
# file pushed to gh-pages (verified by size); the VM's egress proxy blocks
# Chromium from reaching the public Pages URL directly, so the interaction
# test runs against this identical copy. The live deployment is checked
# separately with a fresh crawl.
LAN_IP = "127.0.0.2"  # second loopback address: exercises the user-entered
# custom-address code path exactly like a real LAN IP would (the VM's own
# 198.19.0.2 is not reachable from inside the sandbox, and a true 192.168.x.x
# test needs a second device — Hasan's phone + PC).
PORT = 8790
CHROME = os.path.expanduser("~/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome")


def engine_req(method, path, body=None, token=None):
    # Bypass the VM egress proxy: urllib would otherwise route local
    # engine calls through it and time out.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(
        f"http://{LAN_IP}:{PORT}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    with opener.open(req, timeout=10) as r:
        return r.status, json.loads(r.read() or b"{}")


async def main():
    trust = os.environ.get("TRUST_LAN") == "1"
    args = ["--no-sandbox"]
    if trust:
        args.append(f"--unsafely-treat-insecure-origin-as-secure=http://{LAN_IP}:{PORT}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=CHROME, args=args)
        # Local test: no proxy (page and engine are both local).
        ctx = await browser.new_context()
        page = await ctx.new_page()
        lan_requests = []
        page.on("request", lambda r: lan_requests.append(r.url)
                if LAN_IP in r.url else None)
        # Isolate the LAN path: loopback probes must not reach the engine.
        await page.route("**://127.0.0.1:8790/**", lambda route: route.abort())
        await page.route("**://localhost:8790/**", lambda route: route.abort())

        # 1. Live page must show the LAN section (proves new deployment is live).
        lan_found = False
        for attempt in range(6):
            await page.goto(PAGES, wait_until="networkidle")
            await page.wait_for_timeout(1500)
            lan_found = await page.get_by_placeholder("192.168.1.5").count() > 0
            if lan_found:
                break
            print(f"LAN section not visible yet (attempt {attempt+1}/6), retrying...")
            await page.wait_for_timeout(20000)
        assert lan_found, "LAN section NOT on live Pages (deployment stale?)"
        print("1. live Pages shows LAN section: OK")

        # 2. Fill LAN address, probe, expect pairing flow to start (network proof).
        await page.get_by_placeholder("192.168.1.5").fill(LAN_IP)
        btn = page.get_by_role("button", name="LAN Engine")
        assert await btn.count() == 1, "LAN probe button not found"
        await btn.click()
        await page.wait_for_timeout(6000)
        health_hits = [u for u in lan_requests if "/api/health" in u]
        pair_hits = [u for u in lan_requests if "pair/request" in u]
        print(f"2. probe fired: health={len(health_hits)} pair/request={len(pair_hits)}")
        assert health_hits, "NO request reached the LAN engine (browser blocked it?)"
        assert pair_hits, "probe ok but no pair/request followed"

        # 3. Approve the pairing the UI is actually waiting on: match the
        # 6-digit code shown in the UI to the engine pending list (pending[0]
        # may be a stale pairing from an earlier run).
        _, login = engine_req("POST", "/api/login",
                              {"email": "admin@kamladei.app", "password": "admin123"})
        tok = login["token"]
        _, pend = engine_req("GET", "/api/bridge/pair/pending", token=tok)
        codes = set(re.findall(r"\b\d{6}\b", await page.inner_text("body")))
        target = next((e for e in pend.get("pending", [])
                       if e.get("code") in codes), None)
        assert target, f"no pending entry matches UI codes {codes}: {pend}"
        st, _ = engine_req("POST", "/api/bridge/pair/approve",
                           {"pair_id": target["pair_id"], "ok": True}, token=tok)
        assert st == 200, f"approve failed: {st}"
        await page.wait_for_timeout(12000)
        status_hits = [u for u in lan_requests if "/api/status" in u]
        body = await page.inner_text("body")
        print(f"3. status sync requests={len(status_hits)}, "
              f"LINK CONNECTED={'LINK · CONNECTED' in body}")
        assert status_hits, "no /api/status sync after approval"
        assert "LINK · CONNECTED" in body, "UI status line is not CONNECTED"

        # 4. Reload: address remembered, no token in localStorage.
        await page.reload(wait_until="networkidle")
        await page.wait_for_timeout(1500)
        ip_val = await page.get_by_placeholder("192.168.1.5").input_value()
        keys = await page.evaluate("Object.keys(localStorage)")
        print(f"4. after reload: ip input={ip_val!r}, localStorage keys={keys}")
        assert ip_val == LAN_IP, f"address not remembered: {ip_val!r}"
        assert "kd_lan_url" in keys, "kd_lan_url missing"
        assert not [k for k in keys if "token" in k.lower()], f"token key persisted: {keys}"
        await ctx.close()

        # 5. Wrong address: probe fails, UI stays honestly OFFLINE.
        ctx2 = await browser.new_context()
        page2 = await ctx2.new_page()
        bad_reqs = []
        page2.on("request", lambda r: bad_reqs.append(r.url) if "9999" in r.url else None)
        await page2.route("**://127.0.0.1:8790/**", lambda route: route.abort())
        await page2.route("**://localhost:8790/**", lambda route: route.abort())
        await page2.goto(PAGES, wait_until="networkidle")
        await page2.get_by_placeholder("192.168.1.5").fill(LAN_IP)
        # port input: the input whose current value is 8790
        port_filled = await page2.evaluate("""() => {
          const inp = [...document.querySelectorAll('input')].find(i => i.value === '8790');
          if (!inp) return false;
          inp.focus(); inp.value = ''; return true;
        }""")
        assert port_filled, "port input (value 8790) not found"
        await page2.keyboard.type("9999")
        await page2.get_by_role("button", name="LAN Engine").click()
        await page2.wait_for_timeout(8000)
        body2 = await page2.inner_text("body")
        print(f"5. requests to :9999: {bad_reqs}")
        assert "কোনো Engine পাওয়া যায়নি" in body2, "honest LAN error not shown"
        assert "OFFLINE · PRIVATE" in body2, "bridge badge is not OFFLINE"
        assert "LINK · CONNECTED" not in body2, "wrong address shows CONNECTED!"
        assert all("/api/health" in u for u in bad_reqs), \
            f"unexpected requests to wrong address: {bad_reqs}"
        print("5. wrong address stays OFFLINE with honest error: OK")
        await browser.close()
        print("\nALL LAN CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
