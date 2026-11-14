# Kamla Dei — সম্পূর্ণ করার সুযোগ: যাচাইকৃত সারাংশ (Spec)

**তারিখ:** 2026-11-14
**পদ্ধতি:** Superpowers (obra/superpowers, MIT) — brainstorm → spec → plan → TDD → verification
**সিদ্ধান্তের ভিত্তি:** সরাসরি যাচাই — Superpowers repo clone করে পড়া হয়েছে; Kamla Dei engine কোড, GitHub Pages UI, ও GOAL.md পড়া হয়েছে।

## 1. Superpowers আসলে কী (যাচাইকৃত)

- Superpowers **কোনো অ্যাপ, সার্ভার বা মডেল নয়** — এটা ১৫টা স্কিল (markdown নির্দেশনা) + কাজের পদ্ধতি, যা Claude Code / Antigravity / Codex / Cursor-এর মতো coding agent-এর ভেতরে plugin হিসেবে বসে।
- এটা নিজে থেকে কিছু বানায় না। এটা **এজেন্টকে** নিয়ম মেনে কাজ করায়: brainstorm → ছোট ভাগে spec → plan (TDD, YAGNI, DRY) → subagent দিয়ে implementation → verification-before-completion।
- তাই "Superpowers দিয়ে Kamla Dei সম্পূর্ণ করা" মানে: **এই পদ্ধতি অনুসরণ করে বাকি কাজ শেষ করা** — কোনো install-and-done বোতাম নেই।

## 2. Kamla Dei-র বর্তমান অবস্থা (যাচাইকৃত, 2026-11-14)

- **Engine v1.3.3** (`~/workspace/kamla-dei/`, GitHub `KingKibria/kamla-dei`, public): ২২টা টুল, Groq+Xkiro key-pool brain router, HMAC auth, license keys, bridge endpoints, keyless pairing — সব লোকালি E2E যাচাইকৃত (2026-10-22/23)।
- **Engine LAN-প্রস্তুত (কোডে যাচাইকৃত):** `ThreadingHTTPServer(("0.0.0.0", port))` + সব response-এ `Access-Control-Allow-Private-Network: true` + OPTIONS preflight হ্যান্ডলার — ফোনের ব্রাউজার থেকে LAN ঠিকানায় ডাকা কারিগরিভাবে সম্ভব।
- **UI** (`kamla-dei-ui-design` artifact): Jarvis HUD ডিজাইন, ডেমো অ্যাপ + আসল execution plane, Hasan অনুমোদিত। **GitHub Pages লাইভ যাচাইকৃত** (2026-11-14): https://kingkibria.github.io/kamla-dei/
- **START.bat** শক্ত bootstrap: bundled Python → `py -3` → system `python` → python.org থেকে 3.12.7 embeddable ডাউনলোড।

## 3. কী সম্পূর্ণ করা যায় (এই spec-এর আওতা)

1. **Android LAN host অপশন** — GOAL.md-এর পরের ছোট ধাপ: ফোনের ব্রাউজার থেকে PC-র LAN ঠিকানায় (যেমন `http://192.168.1.5:8790`) UI চালিয়ে Connect। Engine-দিক প্রস্তুত; শুধু UI-তে LAN ঠিকানা বসানোর জায়গা + probe লাগবে।
2. **সম্পূর্ণ regression যাচাই, নতুন প্রমাণসহ** — engine boot → health → status → bridge auth (200/401/403) → pairing সম্পূর্ণ চক্র → approval-সহ চ্যাট → ২২ টুল → version 1.3.3 → PNA preflight। পুরনো যাচাইয়ের ওপর ভরসা নয়, নতুন করে চালিয়ে প্রমাণ।
3. **এই spec + implementation plan repo-তে সংরক্ষণ** — `docs/superpowers/` — যাতে পরের কাজ একই পদ্ধতিতে এগোয়।

## 4. কী সম্পূর্ণ করা যায় না (Hasan ছাড়া অসম্ভব — সৎ সীমা)

1. **প্রথম লাইভ PC connect টেস্ট** — তার PC-তে Launcher চালানো, স্ক্রিনে Allow চাপা, স্ক্রিনশট পাঠানো। 2026-10-23 থেকে তার হাতে আটকে আছে। এটা ছাড়া "সম্পূর্ণ" দাবি করা যাবে না।
2. **আসল Groq key দিয়ে success-path টেস্ট + টোকেন রিপোর্ট** — তার key, তার PC।
3. **Pricing সিদ্ধান্ত** (প্রস্তাব ৳0/300/800) ও **bKash/manual payment ফ্লো** — তার সিদ্ধান্ত ছাড়া বানানো যাবে না।
4. **Beta + public launch** — উপরেরগুলো শেষ হলে, তার সম্মতিতে।

## 5. সিদ্ধান্ত

**আংশিক হ্যাঁ:** Superpowers পদ্ধতিতে Kamla Dei-র **সব বাকি কাজ, যা Hasan-এর PC/সিদ্ধান্ত ছাড়া করা যায়**, সম্পূর্ণ করা সম্ভব — এবং এই spec অনুযায়ী করা হবে। **সম্পূর্ণ রূপে সম্পূর্ণ** দাবি করা যাবে না, যতক্ষণ না ৪ নম্বর সেকশনের আইটেমগুলো শেষ হয়। কোনো দাবি verification ছাড়া করা হবে না (verification-before-completion)।
