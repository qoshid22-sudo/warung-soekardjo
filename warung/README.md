# Warung Soekardjo – Sistem Pesan Online + Kasir

Backend Python (hanya library bawaan, **tanpa `pip install`**) + database SQLite.

## Menjalankan
```bash
cd warung
ADMIN_PASSWORD='password-kuat-minimal-10-karakter' python3 server.py
```
- Pelanggan: `http://localhost:8000/`  → jadikan QR dari alamat ini
- Kasir/admin: `http://localhost:8000/kasir`
- Jika `ADMIN_PASSWORD` tidak diisi, password acak dicetak **sekali** di terminal saat pertama jalan.
- Butuh Python 3.8+. Data tersimpan di `warung.db` (cadangkan file ini secara berkala).

## Variabel lingkungan
| Variabel | Fungsi | Default |
|---|---|---|
| `ADMIN_PASSWORD` | Password admin awal (dipakai hanya saat database baru) | acak |
| `HOST` / `PORT` | Alamat & port | `127.0.0.1` / `8000` |
| `WARUNG_DB` | Lokasi file database | `./warung.db` |
| `SECURE_COOKIE=1` | Cookie hanya lewat HTTPS + header HSTS | `0` |
| `TRUSTED_PROXY=1` | Percaya header `X-Forwarded-For` dari reverse proxy | `0` |

## Go-live (wajib HTTPS)
1. Sewa VPS kecil (atau hosting Python seperti Railway / Render / PythonAnywhere).
2. Jalankan `server.py` di `127.0.0.1:8000`, dengan `SECURE_COOKIE=1 TRUSTED_PROXY=1`.
3. Pasang reverse proxy dengan sertifikat HTTPS otomatis, contoh **Caddy**:
   ```
   warungsoekardjo.com {
       reverse_proxy 127.0.0.1:8000
   }
   ```
4. Buat QR dari `https://warungsoekardjo.com/`.
5. Jalankan sebagai service (systemd) agar otomatis hidup kembali.

## Fitur keamanan
- Password admin di-hash **scrypt** + salt; perbandingan waktu-konstan.
- Login dibatasi 5 percobaan / 5 menit per IP; sesi acak 256-bit (hanya hash-nya disimpan), cookie `HttpOnly` + `SameSite=Strict`, kedaluwarsa 8 jam.
- Perlindungan **CSRF** (token per sesi + pengecekan `Origin`).
- Seluruh query SQL berparameter (anti SQL injection).
- **Harga selalu dihitung server dari database**; harga dari browser diabaikan.
- Validasi ketat semua input (tipe, panjang, daftar nilai yang diizinkan), batas ukuran body 16 KB, batas pesanan per IP (8 / 10 menit), batas antrean pesanan baru.
- Output di browser di-escape (anti XSS) + **Content-Security-Policy** ketat (tanpa script/style inline), `X-Frame-Options`, `nosniff`, dll.
- Path traversal diblokir; hanya folder `static/` yang disajikan.
- Pelacakan pesanan memakai kode acak 10 karakter; data pribadi (nama, HP, alamat) tidak pernah ditampilkan ke publik.
- Pesan error tidak membocorkan detail internal.

## Struktur
```
server.py            backend + API
static/pesan.html/js halaman pelanggan (pilih antar / ambil sendiri, lacak status)
static/kasir.html/js panel admin (login, pesanan, menu, laporan, ganti password)
static/style.css     tampilan bersama
```

## Catatan
- Setelah deploy, ganti password dari tab **Akun**.
- Pesanan walk-in (tanpa online) belum ada input manual di kasir; bisa ditambahkan.

## Pembayaran
- Metode: **Tunai**, **QRIS** (barcode), **Transfer bank** (pelanggan memilih bank, mis. BRI / BCA). Atur rekening & nomor WA di `config.json`.
- Taruh gambar QRIS asli di `static/qris.png`. Selama belum ada, ditampilkan gambar **contoh** (`static/qris-contoh.svg`); jangan go-live sebelum diganti.
- **QRIS & Transfer = bayar dulu.** Pesanan berstatus `menunggu` dan tidak bisa diproses admin sampai pembayaran diterima (tombol *Lunas ...*). Pelanggan bisa menekan "Saya sudah bayar" (admin melihat tanda ✋). Pesanan yang tidak dibayar otomatis batal setelah 60 menit (`PAY_TIMEOUT_MIN`).
- **Tunai**: pesanan langsung berstatus `baru`; bayar saat diantar / diambil.
