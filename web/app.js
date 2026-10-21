// Kamla Dei — unified app client
let token = localStorage.getItem('kd_token') || '';
let me = null;
let curChat = null, lastId = 0;
let authMode = 'login';
let ttsOn = false, micLang = 'bn-BD', rec = null, listening = false;
const $ = id => document.getElementById(id);

async function api(method, path, data) {
  const r = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json',
               ...(token ? { 'Authorization': 'Bearer ' + token } : {}) },
    body: data ? JSON.stringify(data) : undefined
  });
  const out = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(out.error || ('HTTP ' + r.status));
  return out;
}

/* ---------- auth ---------- */
function authTab(mode) {
  authMode = mode;
  $('tabLogin').classList.toggle('on', mode === 'login');
  $('tabReg').classList.toggle('on', mode === 'register');
  $('aName').classList.toggle('hidden', mode === 'login');
  $('aGo').textContent = mode === 'login' ? 'লগইন' : 'অ্যাকাউন্ট খোলো';
  $('aErr').textContent = '';
}
async function doAuth() {
  const email = $('aEmail').value.trim(), pw = $('aPw').value, name = $('aName').value.trim();
  try {
    const out = authMode === 'login'
      ? await api('POST', '/api/login', { email, password: pw })
      : await api('POST', '/api/register', { name, email, password: pw });
    token = out.token; localStorage.setItem('kd_token', token);
    await boot();
  } catch (e) { $('aErr').textContent = e.message; }
}
$('aPw').addEventListener('keydown', e => { if (e.key === 'Enter') doAuth(); });
function logout() {
  token = ''; localStorage.removeItem('kd_token');
  curChat = null;
  $('shell').classList.add('hidden');
  $('authScreen').classList.remove('hidden');
}

/* ---------- boot / views ---------- */
async function boot() {
  me = await api('GET', '/api/me');
  $('authScreen').classList.add('hidden');
  $('shell').classList.remove('hidden');
  $('uName').textContent = me.name;
  $('uPlan').textContent = me.plan_name;
  $('adminNav').classList.toggle('hidden', me.role !== 'admin');
  $('brainBadge').textContent = me.brain === 'live'
    ? '🟢 ' + (me.brain_info || 'আসল ব্রেইন') : '🟡 ডেমো মোড';
  $('dPlan').textContent = me.plan_name + (me.sub_active ? '' : ' (মেয়াদ শেষ)');
  $('dExp').textContent = 'মেয়াদ: ' + (me.expires_at ? new Date(me.expires_at).toLocaleDateString('bn-BD') : '—');
  await loadChats();
  if (!curChat) { const c = await api('POST', '/api/chats', {}); await openChat(c.id); }
  showView('chat');
  renderPlans();
}
function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
  $('view-' + name).classList.remove('hidden');
  document.querySelectorAll('aside .navbtn[data-nav]').forEach(b =>
    b.classList.toggle('active', b.dataset.nav === name));
  if (name === 'files') loadFiles();
  if (name === 'admin') loadAdmin();
}

/* ---------- chats ---------- */
async function loadChats() {
  const { chats } = await api('GET', '/api/chats');
  $('chatList').innerHTML = chats.map(c =>
    `<div class="chatitem${c.id === curChat ? ' on' : ''}" onclick="openChat(${c.id})" title="${esc(c.title)}">${esc(c.title)}</div>`).join('')
    || '<div class="muted" style="padding:8px">কোনো চ্যাট নেই</div>';
  return chats;
}
async function newChat() {
  const c = await api('POST', '/api/chats', {});
  await openChat(c.id);
}
async function openChat(id) {
  curChat = id; lastId = 0;
  $('msgs').innerHTML = '';
  $('approval').classList.add('hidden');
  const chats = await loadChats();
  const c = chats.find(x => x.id === id);
  $('chatTitle').textContent = c ? c.title : 'নতুন চ্যাট';
  poll();
}
function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

function addMsg(m) {
  const d = document.createElement('div');
  d.className = 'msg ' + m.who;
  d.textContent = m.text;
  $('msgs').appendChild(d);
  $('msgs').scrollTop = $('msgs').scrollHeight;
  if (m.who === 'agent') speak(m.text);
}
async function poll() {
  if (!curChat) return;
  try {
    const data = await api('GET', `/api/chats/${curChat}/poll?since=${lastId}`);
    for (const m of data.msgs) { addMsg(m); lastId = m.id; }
    $('typing').classList.toggle('hidden', !data.busy);
    $('quota').textContent = `আজ: ${data.used}`;
    if (data.approval) {
      $('apprTxt').textContent = data.approval.text;
      $('approval').classList.remove('hidden');
    } else $('approval').classList.add('hidden');
  } catch (e) {}
}
setInterval(() => { if (curChat && !$('shell').classList.contains('hidden')) poll(); }, 800);

async function sendMsg() {
  const inp = $('inp');
  const text = inp.value.trim();
  if (!text || !curChat) return;
  inp.value = '';
  try {
    await api('POST', `/api/chats/${curChat}/send`, { text });
  } catch (e) {
    addMsg({ who: 'system', text: '⚠️ ' + e.message });
  }
  poll();
}
$('inp').addEventListener('keydown', e => { if (e.key === 'Enter') sendMsg(); });

async function decide(ok) {
  await api('POST', `/api/chats/${curChat}/approve`, { ok });
  poll();
}

/* ---------- voice ---------- */
function speak(text) {
  if (!ttsOn || !('speechSynthesis' in window)) return;
  const clean = text.replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/gu, '').slice(0, 400);
  if (!clean.trim()) return;
  const u = new SpeechSynthesisUtterance(clean);
  u.lang = 'bn-BD';
  speechSynthesis.cancel(); speechSynthesis.speak(u);
}
function toggleTts() {
  ttsOn = !ttsOn;
  $('ttsBtn').textContent = ttsOn ? '🔊' : '🔇';
  $('ttsBtn').classList.toggle('on', ttsOn);
  if (!ttsOn && 'speechSynthesis' in window) speechSynthesis.cancel();
}
function toggleLang() {
  micLang = micLang === 'bn-BD' ? 'en-US' : 'bn-BD';
  $('langBtn').textContent = micLang === 'bn-BD' ? 'বাং' : 'EN';
}
function toggleMic() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { alert('Chrome/Edge-এ ভয়েস কাজ করে'); return; }
  if (listening) { rec.stop(); return; }
  rec = new SR(); rec.lang = micLang; rec.interimResults = false;
  rec.onresult = e => { $('inp').value = e.results[0][0].transcript; sendMsg(); };
  rec.onend = rec.onerror = () => { listening = false; $('micBtn').classList.remove('rec'); };
  listening = true; $('micBtn').classList.add('rec'); rec.start();
}

/* ---------- files ---------- */
async function loadFiles() {
  try {
    const { files } = await api('GET', '/api/files');
    $('fileList').innerHTML = files.map(f =>
      `<div class="frow">📄 ${esc(f.path)}<span class="sz">${(f.size / 1024).toFixed(1)} KB</span>
       <button class="btn ghost" onclick="dlFile('${esc(f.path)}')">⬇️</button></div>`).join('')
      || '<p class="muted">এখনো কোনো ফাইল নেই — চ্যাটে এজেন্টকে কিছু বানাতে বলো।</p>';
  } catch (e) {}
}
async function dlFile(path) {
  const r = await fetch('/api/files/download?path=' + encodeURIComponent(path),
    { headers: { 'Authorization': 'Bearer ' + token } });
  const blob = await r.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = path.split('/').pop();
  a.click();
}
async function uploadFile() {
  const f = $('upFile').files[0];
  if (!f) return;
  const buf = await f.arrayBuffer();
  let bin = ''; const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 8192)
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
  try {
    await api('POST', '/api/files/upload', { name: f.name, content_b64: btoa(bin) });
    loadFiles();
  } catch (e) { alert(e.message); }
  $('upFile').value = '';
}

/* ---------- plan ---------- */
const PLAN_FEATS = {
  free: ['দিনে ২০টা এজেন্ট টাস্ক', '১টা ডিভাইস'], 
  pro: ['দিনে ৫০০ এজেন্ট টাস্ক', '২টা ডিভাইস', 'সব ২২টা টুল'],
  family: ['দিনে ১০০০ এজেন্ট টাস্ক', '৫টা ডিভাইস', 'সব টুল + প্রায়োরিটি']
};
async function renderPlans() {
  try {
    const { plans } = await api('GET', '/api/plans');
    $('planCards').innerHTML = Object.entries(plans).map(([k, p]) => `
      <div class="card">
        <h3>${k === 'free' ? '🆓' : k === 'pro' ? '⭐' : '👑'} ${p.name}</h3>
        <div class="price">${p.price === 0 ? '৳০' : '৳' + p.price + '<span style="font-size:14px;color:#9aa5c0">/মাস</span>'}</div>
        <ul>${PLAN_FEATS[k].map(f => '<li>✅ ' + f + '</li>').join('')}</ul>
      </div>`).join('');
  } catch (e) {}
}
async function redeem() {
  const code = $('keyInp').value.trim();
  if (!code) return;
  try {
    const out = await api('POST', '/api/redeem', { code });
    $('keyMsg').innerHTML = `<p style="color:#86efac;margin-top:10px">✅ ${out.plan} active! মেয়াদ: ${new Date(out.expires_at).toLocaleDateString('bn-BD')}</p>`;
    await boot();
  } catch (e) { $('keyMsg').innerHTML = `<p class="err" style="margin-top:10px">❌ ${e.message}</p>`; }
}

/* ---------- admin ---------- */
async function genKeys() {
  try {
    const out = await api('POST', '/api/admin/keys',
      { plan: $('kPlan').value, days: +$('kDays').value, count: +$('kCount').value });
    $('newKeys').textContent = out.codes.join('\n');
    loadAdmin();
  } catch (e) { alert(e.message); }
}
async function revoke(code) {
  if (!confirm('বাতিল করবে? ' + code)) return;
  await api('POST', '/api/admin/revoke', { code });
  loadAdmin();
}
async function loadAdmin() {
  try {
    const ku = await api('GET', '/api/admin/keys');
    $('keyList').innerHTML = '<table><tr><th>Code</th><th>Plan</th><th>দিন</th><th>অবস্থা</th><th></th></tr>' +
      ku.keys.map(k => `<tr><td>${k.code}</td><td>${k.plan}</td><td>${k.days}</td>
        <td>${k.revoked ? '🚫 বাতিল' : k.used_by ? '✅ ব্যবহৃত (#' + k.used_by + ')' : '🆕 নতুন'}</td>
        <td>${k.revoked ? '' : `<button class="btn ghost" onclick="revoke('${k.code}')">বাতিল</button>`}</td></tr>`).join('') + '</table>';
    const uu = await api('GET', '/api/admin/users');
    $('userList').innerHTML = '<table><tr><th>#</th><th>নাম</th><th>ইমেইল</th><th>Plan</th><th>মেয়াদ</th></tr>' +
      uu.users.map(u => `<tr><td>${u.id}</td><td>${esc(u.name)}${u.role === 'admin' ? ' 👑' : ''}</td><td>${esc(u.email)}</td><td>${u.plan}</td><td>${u.expires_at ? new Date(u.expires_at).toLocaleDateString('bn-BD') : '—'}</td></tr>`).join('') + '</table>';
  } catch (e) {}
}

/* ---------- boot ---------- */
if (token) boot().catch(() => { localStorage.removeItem('kd_token'); token = ''; });
