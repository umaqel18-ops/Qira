#!/usr/bin/env python3
"""Qira local/LAN prototype server. Uses only the Python standard library."""
from __future__ import annotations
import base64, copy, hashlib, hmac, json, os, secrets, sqlite3, time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parent
HTML_FILE = BASE / 'static' / 'index.html'
DB_FILE = BASE / 'qira.sqlite3'
UPLOAD_DIR = BASE / 'uploads'
MUSIC_FILE = UPLOAD_DIR / 'site_music.bin'
HOST = os.environ.get('QIRA_HOST', '0.0.0.0')
PORT = int(os.environ.get('QIRA_PORT', '8080'))
SESSION_HOURS = int(os.environ.get('QIRA_SESSION_HOURS', '48'))
COOKIE_SECURE = os.environ.get('QIRA_COOKIE_SECURE', '0') == '1'
ADMIN_USERNAME = os.environ.get('QIRA_ADMIN_USERNAME', 'LORD').strip() or 'LORD'
ADMIN_PASSWORDS = (os.environ.get('QIRA_ADMIN_PASSWORD_1') or '1045', os.environ.get('QIRA_ADMIN_PASSWORD_2') or '1946', os.environ.get('QIRA_ADMIN_PASSWORD_3') or '1947')
STAFF_CODE = os.environ.get('QIRA_STAFF_CODE', 'QIRA-STAFF-2026').strip().upper()
MAX_BODY = 10 * 1024 * 1024


def default_logo_data():
    logo_path = BASE / 'static' / 'qira-logo.webp'
    if not logo_path.exists():
        return ''
    return 'data:image/webp;base64,' + base64.b64encode(logo_path.read_bytes()).decode('ascii')


def hash_admin_password(value, salt_hex=None):
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', str(value).encode('utf-8'), salt, 180_000)
    return salt.hex(), digest.hex()


def verify_admin_password(value, salt_hex, expected_hex):
    _, digest = hash_admin_password(value, salt_hex)
    return hmac.compare_digest(digest, expected_hex)


def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def seed_state():
    now = iso_now()
    return {
        'version': '1.1.0',
        'settings': {
            'siteName': 'Qira', 'logo': default_logo_data(), 'primary': '#a98236', 'secondary': '#efe2c0',
            'background': '#f7f2e7', 'snow': True, 'snowSize': 2, 'snowSpeed': 9,
            'offlineMessage': 'لا يوجد اتصال بالإنترنت', 'offlineSymbol': '◉',
            'defaultQuote': 'كل خطوة صغيرة تقرّبك من مستقبل أكبر.'
        },
        'invites': [
            {'code': STAFF_CODE, 'role': 'staff', 'label': 'موظف تجريبي', 'used': False, 'createdAt': now},
        ],
        'drinks': [
            {'id': 'd1', 'name': 'شاي', 'category': 'hot', 'emoji': '🍵', 'description': 'شاي كلاسيكي يجهز حسب طلبك.', 'createdAt': now, 'enabled': True},
            {'id': 'd2', 'name': 'قهوة', 'category': 'hot', 'emoji': '☕', 'description': 'قهوة يومية بطعم غني.', 'createdAt': now, 'enabled': True},
            {'id': 'd3', 'name': 'نسكافيه', 'category': 'hot', 'emoji': '🥤', 'description': 'مشروب قهوة سريع.', 'createdAt': now, 'enabled': True},
            {'id': 'd4', 'name': 'ماء', 'category': 'cold', 'emoji': '💧', 'description': 'ماء بارد ومنعش.', 'createdAt': now, 'enabled': True},
            {'id': 'd5', 'name': 'عصير برتقال', 'category': 'cold', 'emoji': '🍊', 'description': 'عصير بطعم الحمضيات.', 'createdAt': now, 'enabled': True},
        ],
        'categories': [
            {'id': 'c1', 'name': 'الأعلام', 'color': '#b98d3b', 'emoji': '🏳️', 'createdAt': now},
            {'id': 'c2', 'name': 'بمبات', 'color': '#71869a', 'emoji': '💡', 'createdAt': now},
            {'id': 'c3', 'name': 'أدوات مكتبية', 'color': '#648b70', 'emoji': '✒️', 'createdAt': now},
        ],
        'accessories': [
            {'id': 'a1', 'categoryId': 'c1', 'name': 'علم العراق', 'emoji': '🇮🇶', 'description': 'علم العراق.', 'createdAt': now, 'enabled': True},
            {'id': 'a2', 'categoryId': 'c2', 'name': 'مصباح مكتبي', 'emoji': '💡', 'description': 'مصباح للاستخدام المكتبي.', 'createdAt': now, 'enabled': True},
        ],
        'employees': [
            {'id': 'e1', 'name': 'عباس', 'title': 'موظف مشاريب', 'photo': '', 'hireDate': '2025-03-15', 'start': '08:00', 'end': '16:00', 'active': True, 'code': STAFF_CODE, 'notes': '', 'createdAt': now},
            {'id': 'e2', 'name': 'نور', 'title': 'موظفة خدمة', 'photo': '', 'hireDate': '2025-06-01', 'start': '12:00', 'end': '20:00', 'active': True, 'code': '', 'notes': '', 'createdAt': now},
        ],
        'quotes': [
            {'id': 'q1', 'text': 'تقدّم نحو مستقبلك المشرق، فكل يوم فرصة جديدة.', 'createdAt': now},
            {'id': 'q2', 'text': 'ابتسامتك تصنع فرقًا، وإنجازك يبدأ بخطوة.', 'createdAt': now},
            {'id': 'q3', 'text': 'الأشياء العظيمة تُبنى بالصبر والاستمرار.', 'createdAt': now},
        ],
        'orders': [], 'logs': [], 'profiles': {},
    }


def connect():
    con = sqlite3.connect(DB_FILE, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with connect() as con:
        con.execute('CREATE TABLE IF NOT EXISTS app_state (id INTEGER PRIMARY KEY CHECK(id=1), json TEXT NOT NULL)')
        con.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_json TEXT NOT NULL, expires INTEGER NOT NULL)')
        con.execute('''CREATE TABLE IF NOT EXISTS admin_credentials (
            id INTEGER PRIMARY KEY CHECK(id=1), username TEXT NOT NULL,
            salt1 TEXT NOT NULL, hash1 TEXT NOT NULL,
            salt2 TEXT NOT NULL, hash2 TEXT NOT NULL,
            salt3 TEXT NOT NULL, hash3 TEXT NOT NULL,
            updated_at TEXT NOT NULL)''')
        con.execute('CREATE TABLE IF NOT EXISTS admin_attempts (client_ip TEXT PRIMARY KEY, failures INTEGER NOT NULL, locked_until INTEGER NOT NULL)')
        credential_row = con.execute('SELECT id FROM admin_credentials WHERE id=1').fetchone()
        if credential_row is None:
            encoded = [hash_admin_password(item) for item in ADMIN_PASSWORDS]
            con.execute('INSERT INTO admin_credentials(id,username,salt1,hash1,salt2,hash2,salt3,hash3,updated_at) VALUES(1,?,?,?,?,?,?,?,?)',
                        (ADMIN_USERNAME, encoded[0][0], encoded[0][1], encoded[1][0], encoded[1][1], encoded[2][0], encoded[2][1], iso_now()))
        row = con.execute('SELECT json FROM app_state WHERE id=1').fetchone()
        if row is None:
            con.execute('INSERT INTO app_state(id,json) VALUES(1,?)', (json.dumps(seed_state(), ensure_ascii=False),))
        raw = con.execute('SELECT json FROM app_state WHERE id=1').fetchone()['json']
        state = json.loads(raw)
        # Migrate old local prototypes away from a reusable admin invitation code.
        state['invites'] = [i for i in state.get('invites', []) if i.get('role') != 'admin']
        for i in state.get('invites', []):
            if i.get('label') == 'موظف تجريبي':
                i['code'] = STAFF_CODE
        for e in state.get('employees', []):
            if e.get('id') == 'e1' and (not e.get('code') or e.get('code', '').startswith('QIRA-STAFF')):
                e['code'] = STAFF_CODE
        if not state.setdefault('settings', {}).get('logo'):
            state['settings']['logo'] = default_logo_data()
        if str(state.get('version', '1.0.0')) == '1.0.0':
            state['version'] = '1.1.0'
        con.execute('UPDATE app_state SET json=? WHERE id=1', (json.dumps(state, ensure_ascii=False),))
        # Invalidate pre-upgrade administrator sessions so the multi-stage login is required once.
        for session_row in con.execute('SELECT token,user_json FROM sessions').fetchall():
            try:
                if json.loads(session_row['user_json']).get('role') == 'admin':
                    con.execute('DELETE FROM sessions WHERE token=?', (session_row['token'],))
            except (json.JSONDecodeError, TypeError):
                con.execute('DELETE FROM sessions WHERE token=?', (session_row['token'],))
        con.execute('DELETE FROM sessions WHERE expires < ?', (int(time.time()),))


def read_state():
    with connect() as con:
        row = con.execute('SELECT json FROM app_state WHERE id=1').fetchone()
        return json.loads(row['json'])


def write_state(state):
    with connect() as con:
        con.execute('UPDATE app_state SET json=? WHERE id=1', (json.dumps(state, ensure_ascii=False, separators=(',', ':')),))


def push_log(state, action, detail, user, role):
    logs = state.setdefault('logs', [])
    logs.insert(0, {'id': secrets.token_hex(4).upper(), 'at': iso_now(), 'user': user, 'role': role, 'action': action, 'detail': detail})
    del logs[800:]


def allowed_state(state, user):
    view = copy.deepcopy(state)
    if user.get('role') == 'admin':
        return view
    view['logs'] = []
    view['profiles'] = {}
    if user.get('role') == 'staff':
        view['invites'] = []
    else:
        code = user.get('inviteCode')
        view['invites'] = [i for i in view.get('invites', []) if i.get('code', '').upper() == code]
        view['orders'] = [o for o in view.get('orders', []) if o.get('userCode') == code]
    return view


def public_profile(stored, invite, name, role, employee_id=None, profile_key=''):
    profile = stored.get('profiles', {}).get(profile_key, {})
    return {
        'id': secrets.token_hex(4).upper(), 'name': name,
        'displayName': profile.get('displayName') or name,
        'title': profile.get('title', ''), 'customTitle': profile.get('customTitle', ''),
        'photo': profile.get('photo', ''), 'role': role,
        'inviteCode': invite, 'employeeId': employee_id, 'joinedAt': profile.get('joinedAt') or iso_now(),
        'profileKey': profile_key,
    }


BOOTSTRAP = r'''/* QIRA SERVER API — injected only by app.py, never used by the offline preview */
window.QiraServerAPI = (() => {
  let chain = Promise.resolve();
  async function request(path, options={}) {
    const opts = {credentials:'same-origin', ...options};
    opts.headers = {'Content-Type':'application/json', ...(options.headers||{})};
    const response = await fetch(path, opts);
    let payload = {};
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(payload.error || ('HTTP ' + response.status));
    return payload;
  }
  const api = {
    async login(name, code) { try { return await request('/api/login', {method:'POST', body:JSON.stringify({name,code})}); } catch(e) { return {ok:false,error:e.message}; } },
    async adminLogin(username, passwords) { try { return await request('/api/admin-login', {method:'POST', body:JSON.stringify({username,passwords})}); } catch(e) { return {ok:false,error:e.message}; } },
    async changeAdminSecurity(payload) { return request('/api/admin-security', {method:'POST', body:JSON.stringify(payload)}); },
    async state() { const x = await request('/api/state'); return x.state; },
    saveState(state) { const snapshot = JSON.stringify(state); chain = chain.then(() => request('/api/state',{method:'PUT',body:snapshot})).catch(err => console.warn('Qira sync:',err.message)); return chain; },
    async profile(profile) { return request('/api/profile',{method:'POST',body:JSON.stringify(profile)}); },
    async uploadMusic(file) { if(file.size > 6*1024*1024) throw new Error('اختر ملفًا صوتيًا أصغر من 6MB'); const dataUrl = await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=()=>reject(new Error('تعذرت قراءة الملف'));r.readAsDataURL(file)}); return request('/api/music',{method:'POST',body:JSON.stringify({name:file.name,mime:file.type||'audio/mpeg',data:String(dataUrl).split(',')[1]||''})}); },
    async logout() { try { await chain; await request('/api/logout',{method:'POST',body:'{}'}); } catch (_) {} },
    async restore() { try { const me = await request('/api/me'); if(!me.authenticated) return null; return {user:me.user,state:await api.state()}; } catch (_) { return null; } }
  };
  let knownOrderIds = new Set();
  setInterval(async () => {
    if (!user || $('#modalWrap').classList.contains('open')) return;
    try {
      const latest = await api.state();
      const old = new Set((db.orders||[]).map(o=>o.id));
      if (isStaff() || isAdmin()) {
        const arrived = (latest.orders||[]).filter(o=>!old.has(o.id) && o.status==='pending');
        for(const o of arrived) {
          if (typeof playOrderTone === 'function') playOrderTone();
          toast('طلب جديد: ' + o.itemName + ' — ' + o.userName, '☕');
          if ('Notification' in window && Notification.permission === 'granted') new Notification((latest.settings?.siteName||'Qira')+' · طلب جديد', {body:o.userName+' طلب '+o.itemName+' × '+o.quantity+(o.note?' — '+o.note:''), icon:latest.settings?.logo||undefined, tag:'qira-'+o.id});
        }
      }
      db = latest;
      localStorage.setItem(STORE, JSON.stringify(db));
      applySettings();
      if(currentPage==='staff') renderStaff();
      else if(currentPage==='admin' && isAdmin()) renderAdmin();
      else if(currentPage==='home') renderHome();
      else if(currentPage==='drinks') renderDrinks();
      else if(currentPage==='accessories') renderAccessories();
      else if(currentPage==='employees') renderEmployees();
    } catch (_) {}
  }, 10000);
  api.restore().then(result => {
    if(!result) return;
    user = result.user; db = result.state;
    localStorage.setItem('qira_current_profile', JSON.stringify(user));
    $('#loginScreen').classList.add('hide'); $('#topbar').classList.remove('hide'); $('#mobileNav').classList.remove('hide');
    $('#staffNav').classList.toggle('hide', !(isStaff() || isAdmin()));
    $('#welcomeTitle').textContent = `أهلًا ${user.displayName || user.name}، نورت Qira`;
    applySettings(); nav(user.role === 'staff' ? 'staff' : 'home');
  }).catch(() => {});
  return api;
})();
'''


class Handler(BaseHTTPRequestHandler):
    server_version = 'QiraLocal/1.1'

    def log_message(self, fmt, *args):
        # Keep console output short but useful for debugging local runs.
        print('[Qira] ' + (fmt % args))

    def send_json(self, status, payload, extra_headers=None):
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        if extra_headers:
            for k, v in extra_headers.items(): self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def body_json(self):
        length = int(self.headers.get('Content-Length', '0') or '0')
        if length > MAX_BODY:
            raise ValueError('البيانات كبيرة جدًا. قلّل حجم الصورة أو الملف.')
        if length <= 0: return {}
        raw = self.rfile.read(length)
        try: return json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError): raise ValueError('صيغة البيانات غير صحيحة.')

    def current_user(self):
        cookie = self.headers.get('Cookie', '')
        token = ''
        for part in cookie.split(';'):
            key, sep, value = part.strip().partition('=')
            if sep and key == 'qira_session': token = value
        if not token: return None
        with connect() as con:
            row = con.execute('SELECT user_json, expires FROM sessions WHERE token=?', (token,)).fetchone()
            if not row: return None
            if row['expires'] < int(time.time()):
                con.execute('DELETE FROM sessions WHERE token=?', (token,))
                return None
            return json.loads(row['user_json'])

    def require_user(self):
        user = self.current_user()
        if not user:
            self.send_json(401, {'ok': False, 'error': 'سجّل الدخول أولًا.'})
            return None
        return user

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/' or path == '/index.html':
            html = HTML_FILE.read_text(encoding='utf-8')
            html = html.replace('const SERVER_MODE=false;', 'const SERVER_MODE=true;', 1)
            html = html.replace('/* QIRA_SERVER_BOOTSTRAP */', BOOTSTRAP, 1)
            raw = html.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)
            return
        if path == '/health':
            return self.send_json(200, {'ok': True, 'app': 'Qira', 'time': iso_now()})
        if path == '/api/me':
            user = self.current_user()
            return self.send_json(200, {'authenticated': bool(user), 'user': user})
        if path == '/api/music':
            user = self.require_user()
            if not user: return
            state = read_state()
            if not state.get('settings', {}).get('musicAvailable') or not MUSIC_FILE.exists():
                return self.send_json(404, {'error': 'لم يضف المدير موسيقى بعد.'})
            data = MUSIC_FILE.read_bytes()
            mime = state.get('settings', {}).get('musicMime') or 'audio/mpeg'
            range_header = self.headers.get('Range', '')
            if range_header.startswith('bytes='):
                try:
                    part = range_header[6:].split('-', 1)
                    start = int(part[0] or 0)
                    end = int(part[1]) if len(part) > 1 and part[1] else len(data) - 1
                    if start < 0 or end < start or start >= len(data): raise ValueError()
                    end = min(end, len(data)-1); chunk = data[start:end+1]
                    self.send_response(206); self.send_header('Content-Type', mime); self.send_header('Accept-Ranges','bytes')
                    self.send_header('Content-Range', f'bytes {start}-{end}/{len(data)}'); self.send_header('Content-Length', str(len(chunk))); self.send_header('Cache-Control','private, max-age=3600'); self.end_headers(); self.wfile.write(chunk); return
                except ValueError:
                    self.send_response(416); self.send_header('Content-Range', f'bytes */{len(data)}'); self.end_headers(); return
            self.send_response(200); self.send_header('Content-Type', mime); self.send_header('Accept-Ranges','bytes')
            self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control','private, max-age=3600'); self.end_headers(); self.wfile.write(data); return
        if path == '/api/state':
            user = self.require_user()
            if not user: return
            state = read_state()
            return self.send_json(200, {'state': allowed_state(state, user)})
        self.send_json(404, {'error': 'المسار غير موجود.'})

    def do_POST(self):
        path = urlparse(self.path).path
        try: data = self.body_json()
        except ValueError as e: return self.send_json(400, {'ok': False, 'error': str(e)})
        if path == '/api/admin-login':
            username = str(data.get('username', '')).strip()[:70]
            passwords = data.get('passwords', [])
            if not isinstance(passwords, list) or len(passwords) != 3:
                return self.send_json(400, {'ok': False, 'error': 'أكمل مراحل التحقق الثلاث.'})
            passwords = [str(value)[:128] for value in passwords]
            client_ip = self.client_address[0]
            now = int(time.time())
            with connect() as con:
                attempt = con.execute('SELECT failures,locked_until FROM admin_attempts WHERE client_ip=?', (client_ip,)).fetchone()
                if attempt and int(attempt['locked_until']) > now:
                    wait = int(attempt['locked_until']) - now
                    return self.send_json(429, {'ok': False, 'error': f'تم إيقاف المحاولات مؤقتًا. حاول بعد {max(1, wait // 60)} دقيقة.'})
                credentials = con.execute('SELECT * FROM admin_credentials WHERE id=1').fetchone()
            if not credentials:
                return self.send_json(500, {'ok': False, 'error': 'بيانات دخول المدير غير مهيأة.'})
            username_ok = hmac.compare_digest(username.casefold(), str(credentials['username']).casefold())
            password_results = [
                verify_admin_password(passwords[0], credentials['salt1'], credentials['hash1']),
                verify_admin_password(passwords[1], credentials['salt2'], credentials['hash2']),
                verify_admin_password(passwords[2], credentials['salt3'], credentials['hash3']),
            ]
            if not username_ok or not all(password_results):
                with connect() as con:
                    old = con.execute('SELECT failures FROM admin_attempts WHERE client_ip=?', (client_ip,)).fetchone()
                    failures = (int(old['failures']) if old else 0) + 1
                    locked_until = now + 300 if failures >= 5 else 0
                    con.execute('INSERT OR REPLACE INTO admin_attempts(client_ip,failures,locked_until) VALUES(?,?,?)', (client_ip, failures, locked_until))
                return self.send_json(401, {'ok': False, 'error': 'بيانات المدير غير صحيحة.'})
            with connect() as con:
                con.execute('DELETE FROM admin_attempts WHERE client_ip=?', (client_ip,))
            state = read_state()
            profile_key = 'admin:' + credentials['username'].casefold()
            user = public_profile(state, 'QIRA-ADMIN-SECURE', credentials['username'], 'admin', None, profile_key)
            user['name'] = credentials['username']; user['displayName'] = credentials['username']; user['title'] = 'مدير الموقع'
            push_log(state, 'تسجيل دخول المدير', 'تم اجتياز مراحل التحقق الأربع', user['name'], 'admin')
            write_state(state)
            token = secrets.token_urlsafe(32)
            expires = int(time.time()) + SESSION_HOURS * 3600
            with connect() as con:
                con.execute('INSERT INTO sessions(token,user_json,expires) VALUES(?,?,?)', (token, json.dumps(user, ensure_ascii=False), expires))
            attrs = f'qira_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_HOURS*3600}' + ('; Secure' if COOKIE_SECURE else '')
            return self.send_json(200, {'ok': True, 'user': user}, {'Set-Cookie': attrs})
        if path == '/api/admin-security':
            user = self.require_user()
            if not user: return
            if user.get('role') != 'admin': return self.send_json(403, {'ok': False, 'error': 'تغيير بيانات المدير غير مسموح.'})
            username = str(data.get('username', '')).strip()[:70]
            new_passwords = data.get('passwords', ['', '', ''])
            if not username: return self.send_json(400, {'ok': False, 'error': 'اسم المستخدم مطلوب.'})
            if not isinstance(new_passwords, list) or len(new_passwords) != 3:
                return self.send_json(400, {'ok': False, 'error': 'صيغة كلمات المرور غير صحيحة.'})
            new_passwords = [str(value)[:128].strip() for value in new_passwords]
            if any(value and len(value) < 4 for value in new_passwords):
                return self.send_json(400, {'ok': False, 'error': 'كل كلمة مرور جديدة يجب أن تكون 4 محارف على الأقل.'})
            with connect() as con:
                old = con.execute('SELECT * FROM admin_credentials WHERE id=1').fetchone()
                if not old: return self.send_json(500, {'ok': False, 'error': 'بيانات المدير غير مهيأة.'})
                hashes = []
                for index, value in enumerate(new_passwords, 1):
                    if value:
                        hashes.extend(hash_admin_password(value))
                    else:
                        hashes.extend((old[f'salt{index}'], old[f'hash{index}']))
                con.execute('UPDATE admin_credentials SET username=?,salt1=?,hash1=?,salt2=?,hash2=?,salt3=?,hash3=?,updated_at=? WHERE id=1',
                            (username, *hashes, iso_now()))
                token = self._token_from_cookie()
                user['name'] = username; user['displayName'] = username
                con.execute('UPDATE sessions SET user_json=? WHERE token=?', (json.dumps(user, ensure_ascii=False), token))
            state = read_state()
            push_log(state, 'تغيير بيانات دخول المدير', 'تحديث اسم المستخدم وكلمات المرور الأمنية', username, 'admin')
            write_state(state)
            return self.send_json(200, {'ok': True, 'user': user})
        if path == '/api/login':
            name = str(data.get('name', '')).strip()[:70]
            code = str(data.get('code', '')).strip().upper()[:80]
            if not name or not code: return self.send_json(400, {'ok': False, 'error': 'اكتب الاسم وكود الدعوة.'})
            state = read_state()
            invite = next((i for i in state.get('invites', []) if str(i.get('code', '')).upper() == code), None)
            if not invite: return self.send_json(401, {'ok': False, 'error': 'كود الدعوة غير صحيح.'})
            role = invite.get('role', 'user')
            if role == 'admin': return self.send_json(403, {'ok': False, 'error': 'استخدم زر Admin لتسجيل الدخول الإداري.'})
            if role not in ('user', 'staff'): return self.send_json(401, {'ok': False, 'error': 'صلاحية الدعوة غير صالحة.'})
            profile_key = code if role == 'user' else code + ':' + name.casefold()
            previous_profile = state.setdefault('profiles', {}).get(profile_key)
            if role == 'user' and invite.get('used') and (not previous_profile or str(previous_profile.get('name', '')).casefold() != name.casefold()):
                return self.send_json(409, {'ok': False, 'error': 'كود الدعوة استُخدم من قبل. اطلب كودًا جديدًا من المدير.'})
            if role == 'user' and not invite.get('used'):
                invite['used'] = True; invite['usedBy'] = name; invite['usedAt'] = iso_now()
            state.setdefault('profiles', {})
            prof = state['profiles'].setdefault(profile_key, {'name': name, 'displayName': name, 'title': '', 'customTitle': '', 'photo': '', 'joinedAt': iso_now()})
            prof['name'] = name
            emp = next((e for e in state.get('employees', []) if str(e.get('code', '')).upper() == code), None)
            user = public_profile(state, code, name, role, emp.get('id') if emp else None, profile_key)
            push_log(state, 'تسجيل دخول', f'{name} ({role})', name, role)
            write_state(state)
            token = secrets.token_urlsafe(32)
            expires = int(time.time()) + SESSION_HOURS * 3600
            with connect() as con:
                con.execute('INSERT INTO sessions(token,user_json,expires) VALUES(?,?,?)', (token, json.dumps(user, ensure_ascii=False), expires))
            attrs = f'qira_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_HOURS*3600}' + ('; Secure' if COOKIE_SECURE else '')
            return self.send_json(200, {'ok': True, 'user': user}, {'Set-Cookie': attrs})
        if path == '/api/logout':
            user = self.current_user()
            cookie = self.headers.get('Cookie', '')
            token = ''
            for part in cookie.split(';'):
                key, sep, value = part.strip().partition('=')
                if sep and key == 'qira_session': token = value
            if token:
                with connect() as con: con.execute('DELETE FROM sessions WHERE token=?', (token,))
            if user:
                state = read_state(); push_log(state, 'تسجيل خروج', user.get('displayName') or user.get('name', ''), user.get('name', ''), user.get('role', 'user')); write_state(state)
            attrs = 'qira_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0' + ('; Secure' if COOKIE_SECURE else '')
            return self.send_json(200, {'ok': True}, {'Set-Cookie': attrs})
        if path == '/api/profile':
            user = self.require_user()
            if not user: return
            display = str(data.get('displayName', user.get('name', ''))).strip()[:70] or user.get('name', '')
            title = str(data.get('title', '')).strip()[:80]
            custom = str(data.get('customTitle', '')).strip()[:80]
            photo = str(data.get('photo', ''))
            if len(photo) > 2_000_000: return self.send_json(400, {'ok': False, 'error': 'الصورة كبيرة. استخدم صورة أصغر من 1.5MB.'})
            state = read_state(); key = user.get('profileKey') or user.get('inviteCode')
            profile = state.setdefault('profiles', {}).setdefault(key, {})
            profile.update({'name': user.get('name'), 'displayName': display, 'title': title, 'customTitle': custom, 'photo': photo, 'joinedAt': profile.get('joinedAt') or iso_now()})
            user.update({'displayName': display, 'title': title, 'customTitle': custom, 'photo': photo})
            with connect() as con:
                con.execute('UPDATE sessions SET user_json=? WHERE token=?', (json.dumps(user, ensure_ascii=False), self._token_from_cookie()))
            push_log(state, 'تحديث الملف الشخصي', display, user.get('name', ''), user.get('role', 'user'))
            write_state(state)
            return self.send_json(200, {'ok': True, 'user': user})
        if path == '/api/music':
            user = self.require_user()
            if not user: return
            if user.get('role') != 'admin': return self.send_json(403, {'ok': False, 'error': 'رفع الموسيقى متاح للمدير فقط.'})
            mime = str(data.get('mime', 'audio/mpeg')).split(';', 1)[0].strip().lower()
            if not mime.startswith('audio/'):
                return self.send_json(400, {'ok': False, 'error': 'اختر ملفًا صوتيًا صالحًا.'})
            try: music = base64.b64decode(str(data.get('data', '')), validate=True)
            except Exception: return self.send_json(400, {'ok': False, 'error': 'تعذرت قراءة الملف الصوتي.'})
            if not music or len(music) > 6 * 1024 * 1024:
                return self.send_json(400, {'ok': False, 'error': 'حجم الملف يجب أن يكون أقل من 6MB.'})
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            MUSIC_FILE.write_bytes(music)
            state = read_state()
            state.setdefault('settings', {}).update({'musicAvailable': True, 'musicMime': mime, 'musicName': str(data.get('name', 'music')).replace('\\', '/').split('/')[-1][:120]})
            push_log(state, 'تغيير موسيقى الموقع', state['settings']['musicName'], user.get('name', ''), 'admin')
            write_state(state)
            return self.send_json(200, {'ok': True, 'name': state['settings']['musicName']})
        self.send_json(404, {'ok': False, 'error': 'المسار غير موجود.'})

    def _token_from_cookie(self):
        for part in self.headers.get('Cookie', '').split(';'):
            key, sep, value = part.strip().partition('=')
            if sep and key == 'qira_session': return value
        return ''

    def do_PUT(self):
        if urlparse(self.path).path != '/api/state':
            return self.send_json(404, {'ok': False, 'error': 'المسار غير موجود.'})
        user = self.require_user()
        if not user: return
        try: incoming = self.body_json()
        except ValueError as e: return self.send_json(400, {'ok': False, 'error': str(e)})
        if not isinstance(incoming, dict): return self.send_json(400, {'ok': False, 'error': 'صيغة البيانات غير صحيحة.'})
        role = user.get('role')
        state = read_state()
        if role == 'admin':
            required = ('settings', 'invites', 'drinks', 'categories', 'accessories', 'employees', 'quotes', 'orders', 'logs')
            if any(k not in incoming for k in required): return self.send_json(400, {'ok': False, 'error': 'بيانات الإدارة غير مكتملة.'})
            # Keep profiles server-owned; merge fresh server-side orders/logs so a manager edit
            # cannot erase activity that arrived from another device moments earlier.
            incoming['profiles'] = state.get('profiles', {})
            incoming['version'] = str(incoming.get('version', '1.0.0'))[:30]
            current_orders = {str(o.get('id')): copy.deepcopy(o) for o in state.get('orders', [])}
            for candidate in incoming.get('orders', []):
                if not isinstance(candidate, dict) or not candidate.get('id'): continue
                oid = str(candidate['id'])
                existing = current_orders.get(oid)
                if existing is None:
                    current_orders[oid] = copy.deepcopy(candidate)
                elif str(candidate.get('updatedAt', '')) > str(existing.get('updatedAt', '')):
                    current_orders[oid] = copy.deepcopy(candidate)
            incoming['orders'] = sorted(current_orders.values(), key=lambda o: str(o.get('createdAt', '')), reverse=True)
            current_invites = {str(i.get('code', '')).upper(): i for i in state.get('invites', [])}
            for invite in incoming.get('invites', []):
                old_invite = current_invites.get(str(invite.get('code', '')).upper())
                if old_invite and old_invite.get('used'):
                    invite['used'] = True
                    invite.setdefault('usedBy', old_invite.get('usedBy', ''))
                    invite.setdefault('usedAt', old_invite.get('usedAt', ''))
            log_map = {str(x.get('id')): copy.deepcopy(x) for x in state.get('logs', []) if isinstance(x, dict) and x.get('id')}
            for item in incoming.get('logs', []):
                if isinstance(item, dict) and item.get('id'): log_map[str(item['id'])] = copy.deepcopy(item)
            incoming['logs'] = sorted(log_map.values(), key=lambda x: str(x.get('at', '')), reverse=True)[:800]
            write_state(incoming)
            return self.send_json(200, {'ok': True})
        if role == 'staff':
            new_orders = {o.get('id'): o for o in incoming.get('orders', []) if isinstance(o, dict)}
            for current in state.get('orders', []):
                changed = new_orders.get(current.get('id'))
                if not changed: continue
                requested = changed.get('status')
                if requested in ('pending', 'working', 'done', 'cancelled') and requested != current.get('status'):
                    old = current.get('status', 'pending')
                    current['status'] = requested; current['updatedAt'] = iso_now()
                    push_log(state, 'تحديث حالة طلب', f"{current.get('itemName','طلب')}: {old} ← {requested} | {current.get('userName','')}", user.get('name',''), 'staff')
            write_state(state)
            return self.send_json(200, {'ok': True})
        # Regular users may only create their own validated orders. They cannot change product data,
        # invite codes, other users' orders, the site settings, or audit records.
        existing_ids = {o.get('id') for o in state.get('orders', [])}
        posted = incoming.get('orders', [])
        if not isinstance(posted, list): posted = []
        added = 0
        for candidate in posted:
            if not isinstance(candidate, dict) or candidate.get('id') in existing_ids: continue
            if candidate.get('userCode') != user.get('inviteCode'): continue
            typ = candidate.get('type')
            if typ == 'drink':
                product = next((x for x in state.get('drinks', []) if x.get('id') == candidate.get('itemId') and x.get('enabled', True)), None)
                if not product: continue
                category = 'مشروب حار' if product.get('category') == 'hot' else 'مشروب بارد'
            elif typ == 'accessory':
                product = next((x for x in state.get('accessories', []) if x.get('id') == candidate.get('itemId') and x.get('enabled', True)), None)
                if not product: continue
                cat = next((x for x in state.get('categories', []) if x.get('id') == product.get('categoryId')), None)
                category = cat.get('name', 'ملحقات') if cat else 'ملحقات'
            else: continue
            qty = max(1, min(50, int(candidate.get('quantity', 1) or 1)))
            sugar = str(candidate.get('sugar', '0'))
            if sugar not in ('0', '50', '100'): sugar = '0'
            note = str(candidate.get('note', '')).strip()[:700]
            order = {
                'id': str(candidate.get('id') or secrets.token_hex(4).upper())[:40], 'type': typ,
                'itemId': product['id'], 'itemName': product.get('name', 'منتج'), 'category': category,
                'quantity': qty, 'stevia': bool(candidate.get('stevia')) if typ == 'drink' else False,
                'sugar': sugar if typ == 'drink' else '0', 'note': note,
                'userName': user.get('displayName') or user.get('name', ''), 'userCode': user.get('inviteCode'),
                'role': 'user', 'status': 'pending', 'createdAt': iso_now(), 'updatedAt': iso_now(),
                'quote': str(candidate.get('quote', ''))[:500]
            }
            state.setdefault('orders', []).insert(0, order)
            existing_ids.add(order['id']); added += 1
            push_log(state, 'طلب جديد', f"{order['itemName']} × {qty} من {order['userName']}" + (f" | ملاحظة: {note}" if note else ''), order['userName'], 'user')
            if note:
                push_log(state, 'ملاحظة طلب', f"{order['itemName']}: {note}", order['userName'], 'user')
        write_state(state)
        return self.send_json(200, {'ok': True, 'added': added})


def main():
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print('\nQira is running.')
    print(f'Open on this computer: http://127.0.0.1:{PORT}')
    print(f'Network access (same Wi-Fi): http://<COMPUTER-IP>:{PORT}')
    print(f'Database: {DB_FILE}')
    print('For a public internet deployment, use HTTPS and a production application server; this server is intended for local/LAN prototyping.\n')
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nStopping Qira...')
    finally: server.server_close()

if __name__ == '__main__': main()
