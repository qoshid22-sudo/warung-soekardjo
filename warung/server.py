#!/usr/bin/env python3
"""Warung Soekardjo - backend aman (Python standar + SQLite, tanpa dependensi)."""
import hashlib, hmac, json, os, re, secrets, sqlite3, sys, threading, time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
DB_PATH = os.environ.get("WARUNG_DB", str(BASE / "warung.db"))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
SECURE = os.environ.get("SECURE_COOKIE", "0") == "1"   # aktifkan jika memakai HTTPS
PROXY = os.environ.get("TRUSTED_PROXY", "0") == "1"    # aktifkan jika di belakang Nginx/Caddy
SESSION_TTL = 8 * 3600
MAX_BODY = 16 * 1024
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TYPES = ("Ambil sendiri", "Antar")
PICKUPS = ("Secepatnya", "30 menit lagi", "1 jam lagi", "-")
CATS = ("paket", "ayam", "sayur", "nasi", "minuman")
STATUSES = ("menunggu", "baru", "siap", "selesai", "batal")
PAY_TIMEOUT = int(os.environ.get("PAY_TIMEOUT_MIN", "60")) * 60  # pesanan transfer/QRIS yang tidak dibayar otomatis batal
METHODS = ("Tunai", "QRIS", "Transfer")


def load_config():
    """Baca config.json (rekening bank, QRIS, metode pembayaran aktif)."""
    cfg = {"payments": {"Tunai": True, "QRIS": True, "Transfer": True}, "banks": [], "qris_image": "qris.png", "wa": ""}
    try:
        raw = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {}
    except Exception as e:
        sys.exit(f"config.json tidak valid: {e}")
    if isinstance(raw.get("payments"), dict):
        for m in METHODS:
            if m in raw["payments"]:
                cfg["payments"][m] = raw["payments"][m] is True
    for b in raw.get("banks", []) if isinstance(raw.get("banks"), list) else []:
        if isinstance(b, dict) and all(isinstance(b.get(k), str) and b.get(k).strip() for k in ("bank", "number", "holder")):
            cfg["banks"].append({k: b[k].strip()[:40] for k in ("bank", "number", "holder")})
    if isinstance(raw.get("qris_image"), str):
        cfg["qris_image"] = Path(raw["qris_image"]).name  # hanya nama file di folder static
    if isinstance(raw.get("wa"), str):
        d = re.sub(r"\D", "", raw["wa"])
        cfg["wa"] = ("62" + d[1:] if d.startswith("0") else d)[:15]
    return cfg


CFG = load_config()


def qris_file():
    """Gambar QRIS asli (static/qris.png) atau gambar contoh bila belum diunggah."""
    for f in (CFG["qris_image"], "qris-contoh.svg"):
        if f and (STATIC / f).is_file():
            return f
    return ""


def qris_ok():
    return bool(qris_file())


def enabled_methods():
    out = []
    for m in METHODS:
        if not CFG["payments"].get(m):
            continue
        if m == "Transfer" and not CFG["banks"]:
            continue
        if m == "QRIS" and not qris_ok():
            continue
        out.append(m)
    return out


def pay_info(m, bank=""):
    if m == "Transfer":
        return {"method": m, "banks": [b for b in CFG["banks"] if not bank or b["bank"] == bank]}
    if m == "QRIS":
        return {"method": m, "qris": "/static/" + qris_file() if qris_ok() else ""}
    return {"method": "Tunai", "note": "Bayar tunai saat pesanan diantar / diambil."}

SEED = [
    ("Ayam Goreng", "ayam", 6000, "🍗", "Krispi"), ("Ayam Bakar", "ayam", 6000, "🍖", "Bumbu kecap"),
    ("Ayam Geprek", "ayam", 6000, "🌶️", "Sambal pedas"), ("Ayam Kremes", "ayam", 6000, "🍗", "Kremes renyah"),
    ("Ayam Penyet", "ayam", 6000, "🍗", "Sambal penyet"), ("Ayam Rica", "ayam", 6000, "🌶️", "Rica-rica"),
    ("Ayam Kalasan", "ayam", 6000, "🍖", "Manis gurih"), ("Ayam Pop", "ayam", 6000, "🍗", "Khas Padang"),
    ("Sayur Asem", "sayur", 3000, "🥬", "Segar"), ("Sayur Sop", "sayur", 3000, "🥦", "Kuah bening"),
    ("Tumis Kangkung", "sayur", 3000, "🥗", "Pedas"), ("Pecel", "sayur", 3000, "🥜", "Bumbu kacang"),
    ("Urap", "sayur", 3000, "🥥", "Kelapa"), ("Tumis Buncis", "sayur", 3000, "🥬", "Bawang"),
    ("Capcay", "sayur", 3000, "🥦", "Campur"), ("Cah Kangkung", "sayur", 3000, "🥗", "Bawang putih"),
    ("Nasi Putih", "nasi", 3000, "🍚", "Hangat"), ("Nasi Liwet", "nasi", 5000, "🍚", "Gurih"),
    ("Nasi Uduk", "nasi", 5000, "🍚", "Santan"),
    ("Paket A", "paket", 12000, "📦", "Nasi + Ayam Goreng + Sayur Asem"),
    ("Paket B", "paket", 12000, "📦", "Nasi + Ayam Bakar + Tumis Kangkung"),
    ("Paket C", "paket", 13000, "📦", "Nasi + Ayam Geprek + Pecel"),
    ("Paket D", "paket", 13000, "📦", "Nasi + Ayam Kremes + Sayur Sop"),
    ("Es Teh", "minuman", 3000, "🧋", "Manis dingin"), ("Teh Hangat", "minuman", 2000, "🍵", "Hangat"),
    ("Air Mineral", "minuman", 3000, "💧", "Botol"),
]

# ---------------------------------------------------------------- database
_local = threading.local()


def db():
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(DB_PATH, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        _local.c = c
    return c


def hash_pw(pw, salt=None):
    salt = salt or os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return salt.hex() + "$" + h.hex()


def check_pw(pw, stored):
    try:
        s, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(s), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False


def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS menu(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, cat TEXT NOT NULL,
      price INTEGER NOT NULL CHECK(price>=0), icon TEXT NOT NULL DEFAULT '🍽️', desc TEXT NOT NULL DEFAULT '',
      active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
      phone TEXT NOT NULL, type TEXT NOT NULL, address TEXT NOT NULL, note TEXT NOT NULL, pickup TEXT NOT NULL,
      total INTEGER NOT NULL, status TEXT NOT NULL, paid INTEGER NOT NULL DEFAULT 0, method TEXT NOT NULL DEFAULT '',
      pay TEXT NOT NULL DEFAULT 'Tunai', bank TEXT NOT NULL DEFAULT '', claimed INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS order_items(id INTEGER PRIMARY KEY AUTOINCREMENT,
      order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE, name TEXT NOT NULL, price INTEGER NOT NULL, qty INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status, created);
    """)
    cols = [r[1] for r in c.execute("PRAGMA table_info(orders)")]  # migrasi database lama
    for col, ddl in (('pay', "TEXT NOT NULL DEFAULT 'Tunai'"), ('bank', "TEXT NOT NULL DEFAULT ''"), ('claimed', 'INTEGER NOT NULL DEFAULT 0')):
        if col not in cols:
            c.execute(f'ALTER TABLE orders ADD COLUMN {col} {ddl}')
    if not c.execute("SELECT 1 FROM menu LIMIT 1").fetchone():
        c.executemany("INSERT INTO menu(name,cat,price,icon,desc) VALUES(?,?,?,?,?)", SEED)
    if not c.execute("SELECT 1 FROM settings WHERE key='admin_hash'").fetchone():
        pw = os.environ.get("ADMIN_PASSWORD")
        generated = pw is None
        if generated:
            pw = secrets.token_urlsafe(12)
        elif len(pw) < 10:
            sys.exit("ADMIN_PASSWORD minimal 10 karakter.")
        c.execute("INSERT INTO settings VALUES('admin_hash',?)", (hash_pw(pw),))
        if generated:
            print("=" * 56, "\nPASSWORD ADMIN AWAL (catat, hanya tampil sekali):\n", pw, "\n" + "=" * 56, flush=True)
    c.commit()


# ---------------------------------------------------------------- pembatas laju
class Limiter:
    def __init__(self):
        self.h, self.l = {}, threading.Lock()

    def over(self, key, limit, window):
        now = time.time()
        with self.l:
            q = [t for t in self.h.get(key, []) if now - t < window]
            self.h[key] = q
            return len(q) >= limit

    def add(self, key):
        with self.l:
            self.h.setdefault(key, []).append(time.time())

    def clear(self, key):
        with self.l:
            self.h.pop(key, None)


LIM_LOGIN, LIM_ORDER, LIM_TRACK = Limiter(), Limiter(), Limiter()


def expire_unpaid():
    c = db()
    c.execute("UPDATE orders SET status='batal' WHERE status='menunggu' AND paid=0 AND created<?", (int(time.time()) - PAY_TIMEOUT,))
    c.commit()


class ApiError(Exception):
    def __init__(self, code, msg):
        self.code, self.msg = code, msg


def clean(v, maxlen, required=True, field="Data"):
    if v is None or v == "":
        if required:
            raise ApiError(400, f"{field} wajib diisi")
        return ""
    if not isinstance(v, str):
        raise ApiError(400, f"{field} tidak valid")
    v = re.sub(r"[\x00-\x1f\x7f]", " ", v).strip()
    if required and not v:
        raise ApiError(400, f"{field} wajib diisi")
    if len(v) > maxlen:
        raise ApiError(400, f"{field} terlalu panjang (maks {maxlen} karakter)")
    return v


def as_int(v, lo, hi, field):
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ApiError(400, f"{field} tidak valid")
    return v


MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


class Handler(BaseHTTPRequestHandler):
    server_version = "warung"
    sys_version = ""
    timeout = 10  # tahan serangan koneksi lambat

    # ---- util
    def ip(self):
        if PROXY:
            xf = self.headers.get("X-Forwarded-For", "")
            if xf:
                return xf.split(",")[-1].strip()
        return self.client_address[0]

    def send(self, code, obj=None, raw=None, ctype="application/json; charset=utf-8", extra=None):
        body = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if raw is None else "no-cache")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        if SECURE:
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            raise ApiError(415, "Content-Type harus application/json")
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(400, "Content-Length tidak valid")
        if n <= 0 or n > MAX_BODY:
            raise ApiError(413 if n > MAX_BODY else 400, "Ukuran data tidak valid")
        try:
            d = json.loads(self.rfile.read(n))
        except Exception:
            raise ApiError(400, "JSON tidak valid")
        if not isinstance(d, dict):
            raise ApiError(400, "JSON harus berupa objek")
        return d

    def session(self):
        ck = SimpleCookie(self.headers.get("Cookie", ""))
        if "ws_sid" not in ck:
            return None
        th = hashlib.sha256(ck["ws_sid"].value.encode()).hexdigest()
        return db().execute("SELECT * FROM sessions WHERE token_hash=? AND expires>?", (th, int(time.time()))).fetchone()

    # ---- dispatch
    def handle_any(self, m):
        try:
            u = urlparse(self.path)
            if u.path.startswith("/api/"):
                if m != "GET":
                    o = self.headers.get("Origin")
                    if o and urlparse(o).netloc != self.headers.get("Host"):
                        raise ApiError(403, "Origin ditolak")
                return self.api(m, u.path, parse_qs(u.query))
            if m != "GET":
                raise ApiError(405, "Metode tidak diizinkan")
            return self.static(u.path)
        except ApiError as e:
            self.send(e.code, {"error": e.msg})
        except Exception as e:  # jangan bocorkan detail ke klien
            print("ERROR", type(e).__name__, e, file=sys.stderr)
            self.send(500, {"error": "Terjadi kesalahan pada server"})

    do_GET = lambda s: s.handle_any("GET")
    do_POST = lambda s: s.handle_any("POST")
    do_PUT = lambda s: s.handle_any("PUT")
    do_PATCH = lambda s: s.handle_any("PATCH")
    do_DELETE = lambda s: s.handle_any("DELETE")

    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (self.ip(), (fmt % a).split("?")[0]))

    def static(self, path):
        rel = {"/": "pesan.html", "/pesan": "pesan.html", "/kasir": "kasir.html"}.get(path)
        if rel is None:
            if not path.startswith("/static/"):
                raise ApiError(404, "Tidak ditemukan")
            rel = path[len("/static/"):]
        p = (STATIC / rel).resolve()
        if STATIC not in p.parents or not p.is_file() or p.suffix not in MIME:
            raise ApiError(404, "Tidak ditemukan")
        self.send(200, raw=p.read_bytes(), ctype=MIME[p.suffix])

    # ---- API
    def api(self, m, path, qs):
        if path == "/api/menu" and m == "GET":
            rows = db().execute("SELECT id,name,cat,price,icon,desc FROM menu WHERE active=1 ORDER BY id").fetchall()
            return self.send(200, [dict(r) for r in rows])
        if path == "/api/config" and m == "GET":
            return self.send(200, {"payments": enabled_methods(), "banks": [b["bank"] for b in CFG["banks"]], "wa": CFG["wa"]})
        if path == "/api/orders" and m == "POST":
            return self.create_order(self.body())
        mc = re.fullmatch(r"/api/orders/([A-Z2-9]{10})/claim", path)
        if mc and m == "POST":
            if LIM_TRACK.over(self.ip(), 60, 600):
                raise ApiError(429, "Terlalu banyak permintaan")
            LIM_TRACK.add(self.ip())
            c = db()
            cur = c.execute("UPDATE orders SET claimed=1 WHERE code=? AND status='menunggu' AND paid=0", (mc.group(1),))
            c.commit()
            if not cur.rowcount:
                raise ApiError(409, "Pesanan tidak sedang menunggu pembayaran")
            return self.send(200, {"ok": True})
        mo = re.fullmatch(r"/api/orders/([A-Z2-9]{10})", path)
        if mo and m == "GET":
            return self.track(mo.group(1))
        if path == "/api/login" and m == "POST":
            return self.login(self.body())
        if path.startswith("/api/admin/"):
            s = self.session()
            if not s:
                raise ApiError(401, "Belum login")
            if m != "GET" and not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), s["csrf"]):
                raise ApiError(403, "Token CSRF tidak valid")
            return self.admin(m, path, qs, s)
        raise ApiError(404, "Tidak ditemukan")

    def create_order(self, b):
        ip = self.ip()
        if LIM_ORDER.over(ip, 8, 600):
            raise ApiError(429, "Terlalu banyak pesanan. Coba lagi beberapa menit lagi.")
        c = db()
        if c.execute("SELECT COUNT(*) FROM orders WHERE status IN ('baru','menunggu')").fetchone()[0] >= 200:
            raise ApiError(503, "Warung sedang penuh pesanan. Coba lagi nanti.")
        name = clean(b.get("name"), 60, field="Nama")
        phone = clean(b.get("phone"), 20, field="No. HP")
        if not re.fullmatch(r"\+?[0-9][0-9 \-]{6,18}[0-9]", phone):
            raise ApiError(400, "No. HP tidak valid")
        typ = b.get("type")
        if typ not in TYPES:
            raise ApiError(400, "Jenis pesanan tidak valid")
        address = clean(b.get("address"), 200, required=(typ == "Antar"), field="Alamat") if typ == "Antar" else ""
        pickup = b.get("pickup") if typ == "Ambil sendiri" else "-"
        if pickup not in PICKUPS:
            raise ApiError(400, "Jam ambil tidak valid")
        note = clean(b.get("note"), 200, required=False, field="Catatan")
        pay = b.get("pay")
        if pay not in enabled_methods():
            raise ApiError(400, "Metode pembayaran tidak tersedia")
        bank = b.get("bank") if pay == "Transfer" else ""
        if pay == "Transfer" and bank not in [x["bank"] for x in CFG["banks"]]:
            raise ApiError(400, "Pilih bank tujuan transfer")
        status0 = "menunggu" if pay in ("QRIS", "Transfer") else "baru"  # bayar dulu, baru dikonfirmasi
        items = b.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 30:
            raise ApiError(400, "Pilih minimal satu menu")
        qty = {}
        for it in items:
            if not isinstance(it, dict):
                raise ApiError(400, "Item tidak valid")
            mid, q = as_int(it.get("id"), 1, 10 ** 9, "Menu"), as_int(it.get("qty"), 1, 20, "Jumlah")
            qty[mid] = min(20, qty.get(mid, 0) + q)
        rows = c.execute(f"SELECT id,name,price FROM menu WHERE active=1 AND id IN ({','.join('?' * len(qty))})", list(qty)).fetchall()
        if len(rows) != len(qty):
            raise ApiError(400, "Ada menu yang sudah tidak tersedia. Muat ulang halaman.")
        total = sum(r["price"] * qty[r["id"]] for r in rows)  # harga SELALU dari database
        for _ in range(5):
            code = "".join(secrets.choice(ALPHABET) for _ in range(10))
            try:
                cur = c.execute("INSERT INTO orders(code,name,phone,type,address,note,pickup,total,status,paid,method,pay,bank,created) "
                                "VALUES(?,?,?,?,?,?,?,?,?,0,'',?,?,?)", (code, name, phone, typ, address, note, pickup, total, status0, pay, bank, int(time.time())))
                c.executemany("INSERT INTO order_items(order_id,name,price,qty) VALUES(?,?,?,?)",
                              [(cur.lastrowid, r["name"], r["price"], qty[r["id"]]) for r in rows])
                c.commit()
                break
            except sqlite3.IntegrityError:
                c.rollback()
        else:
            raise ApiError(500, "Gagal menyimpan pesanan")
        LIM_ORDER.add(ip)
        self.send(201, {"code": code, "total": total, "status": status0, "instructions": pay_info(pay, bank)})

    def order_json(self, o, full):
        items = db().execute("SELECT name,price,qty FROM order_items WHERE order_id=?", (o["id"],)).fetchall()
        d = {"code": o["code"], "status": o["status"], "paid": bool(o["paid"]), "type": o["type"], "total": o["total"],
             "created": o["created"], "pay": o["pay"], "bank": o["bank"], "claimed": bool(o["claimed"]), "items": [dict(i) for i in items]}
        if not full and not o["paid"] and o["status"] in ("menunggu", "baru", "siap"):
            d["instructions"] = pay_info(o["pay"], o["bank"])
        if full:
            d.update(id=o["id"], name=o["name"], phone=o["phone"], address=o["address"], note=o["note"],
                     pickup=o["pickup"], method=o["method"])
        return d

    def track(self, code):
        if LIM_TRACK.over(self.ip(), 60, 600):
            raise ApiError(429, "Terlalu banyak permintaan")
        LIM_TRACK.add(self.ip())
        expire_unpaid()
        o = db().execute("SELECT * FROM orders WHERE code=?", (code,)).fetchone()
        if not o:
            raise ApiError(404, "Kode pesanan tidak ditemukan")
        self.send(200, self.order_json(o, False))

    def login(self, b):
        ip = self.ip()
        if LIM_LOGIN.over(ip, 5, 300):
            raise ApiError(429, "Terlalu banyak percobaan login. Coba lagi 5 menit lagi.")
        pw = b.get("password")
        if not isinstance(pw, str) or len(pw) > 200:
            raise ApiError(400, "Password tidak valid")
        c = db()
        if not check_pw(pw, c.execute("SELECT value FROM settings WHERE key='admin_hash'").fetchone()[0]):
            LIM_LOGIN.add(ip)
            time.sleep(0.5)
            raise ApiError(401, "Password salah")
        LIM_LOGIN.clear(ip)
        tok, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        c.execute("DELETE FROM sessions WHERE expires<?", (int(time.time()),))
        c.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(tok.encode()).hexdigest(), csrf, int(time.time()) + SESSION_TTL))
        c.commit()
        ck = f"ws_sid={tok}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}" + ("; Secure" if SECURE else "")
        self.send(200, {"csrf": csrf}, extra={"Set-Cookie": ck})

    def menu_fields(self, b):
        cat = b.get("cat")
        if cat not in CATS:
            raise ApiError(400, "Kategori tidak valid")
        return (clean(b.get("name"), 40, field="Nama menu"), cat, as_int(b.get("price"), 0, 1_000_000, "Harga"),
                clean(b.get("icon"), 8, required=False, field="Ikon") or "🍽️", clean(b.get("desc"), 80, required=False, field="Deskripsi"),
                1 if b.get("active", True) is True else 0)

    def admin(self, m, path, qs, s):
        c = db()
        if path == "/api/admin/me" and m == "GET":
            return self.send(200, {"ok": True, "csrf": s["csrf"]})
        if path == "/api/admin/logout" and m == "POST":
            c.execute("DELETE FROM sessions WHERE token_hash=?", (s["token_hash"],))
            c.commit()
            return self.send(200, {"ok": True}, extra={"Set-Cookie": "ws_sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
        if path == "/api/admin/orders" and m == "GET":
            expire_unpaid()
            f = (qs.get("status") or ["aktif"])[0]
            where = {"aktif": "status IN ('menunggu','baru','siap')", "selesai": "status='selesai'", "batal": "status='batal'"}.get(f, "1=1")
            rows = c.execute(f"SELECT * FROM orders WHERE {where} ORDER BY id DESC LIMIT 200").fetchall()
            return self.send(200, [self.order_json(o, True) for o in rows])
        mo = re.fullmatch(r"/api/admin/orders/(\d+)", path)
        if mo and m == "PATCH":
            b = self.body()
            o = c.execute("SELECT * FROM orders WHERE id=?", (int(mo.group(1)),)).fetchone()
            if not o:
                raise ApiError(404, "Pesanan tidak ditemukan")
            if o["status"] in ("selesai", "batal"):
                raise ApiError(409, "Pesanan sudah ditutup")
            paid, method, status = o["paid"], o["method"], o["status"]
            if b.get("paid") is True:
                if b.get("method") not in METHODS:
                    raise ApiError(400, "Metode pembayaran tidak valid")
                paid, method = 1, b["method"]
                if status == "menunggu":
                    status = "baru"  # pembayaran diterima -> pesanan dikonfirmasi
            if "status" in b:
                if b["status"] not in ("baru", "siap", "selesai", "batal"):
                    raise ApiError(400, "Status tidak valid")
                status = b["status"]
            if o["status"] == "menunggu" and not paid and status != "batal":
                raise ApiError(409, "Menunggu pembayaran. Terima pembayaran dulu.")
            if status == "selesai" and not paid:
                raise ApiError(409, "Tandai lunas dulu sebelum selesai")
            c.execute("UPDATE orders SET paid=?,method=?,status=? WHERE id=?", (paid, method, status, o["id"]))
            c.commit()
            return self.send(200, {"ok": True})
        if path == "/api/admin/menu":
            if m == "GET":
                return self.send(200, [dict(r) for r in c.execute("SELECT * FROM menu ORDER BY id")])
            if m == "POST":
                cur = c.execute("INSERT INTO menu(name,cat,price,icon,desc,active) VALUES(?,?,?,?,?,?)", self.menu_fields(self.body()))
                c.commit()
                return self.send(201, {"id": cur.lastrowid})
        mm = re.fullmatch(r"/api/admin/menu/(\d+)", path)
        if mm and m == "PUT":
            c.execute("UPDATE menu SET name=?,cat=?,price=?,icon=?,desc=?,active=? WHERE id=?", self.menu_fields(self.body()) + (int(mm.group(1)),))
            c.commit()
            return self.send(200, {"ok": True})
        if mm and m == "DELETE":
            c.execute("DELETE FROM menu WHERE id=?", (int(mm.group(1)),))
            c.commit()
            return self.send(200, {"ok": True})
        if path == "/api/admin/report" and m == "GET":
            today = "status!='batal' AND date(created,'unixepoch','localtime')=date('now','localtime')"
            r = c.execute(f"SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN paid=1 THEN total END),0) paid, "
                          f"COALESCE(SUM(CASE WHEN paid=0 THEN total END),0) unpaid FROM orders WHERE {today}").fetchone()
            top = c.execute(f"SELECT i.name, SUM(i.qty) q FROM order_items i JOIN orders o ON o.id=i.order_id WHERE {today.replace('status', 'o.status').replace('date(created', 'date(o.created')} GROUP BY i.name ORDER BY q DESC LIMIT 6").fetchall()
            meth = c.execute(f"SELECT method, SUM(total) t FROM orders WHERE {today} AND paid=1 GROUP BY method").fetchall()
            return self.send(200, {"count": r["n"], "paid": r["paid"], "unpaid": r["unpaid"],
                                   "top": [dict(x) for x in top], "methods": [dict(x) for x in meth]})
        if path == "/api/admin/password" and m == "POST":
            b = self.body()
            old, new = b.get("old"), b.get("new")
            if not isinstance(old, str) or not isinstance(new, str) or len(new) < 10 or len(new) > 200:
                raise ApiError(400, "Password baru minimal 10 karakter")
            if not check_pw(old, c.execute("SELECT value FROM settings WHERE key='admin_hash'").fetchone()[0]):
                raise ApiError(403, "Password lama salah")
            c.execute("UPDATE settings SET value=? WHERE key='admin_hash'", (hash_pw(new),))
            c.execute("DELETE FROM sessions WHERE token_hash!=?", (s["token_hash"],))
            c.commit()
            return self.send(200, {"ok": True})
        raise ApiError(404, "Tidak ditemukan")


if __name__ == "__main__":
    init_db()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    srv.daemon_threads = True
    print(f"Warung Soekardjo berjalan di http://{HOST}:{PORT}  (kasir: /kasir)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nBerhenti.")
