(() => {
  const $ = id => document.getElementById(id);
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const rp = n => 'Rp ' + Number(n).toLocaleString('id-ID');
  const CATS = { paket: '📦 Paket', ayam: '🍗 Ayam', sayur: '🥬 Sayur', nasi: '🍚 Nasi', minuman: '🧋 Minuman' };
  const STATUS = { menunggu: '💳 Menunggu pembayaran', baru: '⏳ Menunggu konfirmasi warung', siap: '✅ Pesanan siap', selesai: '🎉 Selesai', batal: '❌ Dibatalkan' };
  let MENU = [], cart = {}, mode = 'Ambil sendiri', cat = 'paket', timer = null, busy = false, pays = [], pay = '', bank = '', cfg = {};

  const toast = m => { const t = $('toast'); t.textContent = m; t.classList.add('show'); clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove('show'), 2200); };
  const store = { get: k => { try { return localStorage.getItem(k) } catch (e) { return null } }, set: (k, v) => { try { localStorage.setItem(k, v) } catch (e) { } }, del: k => { try { localStorage.removeItem(k) } catch (e) { } } };
  async function api(m, u, b) {
    const r = await fetch(u, { method: m, headers: b ? { 'Content-Type': 'application/json' } : {}, body: b ? JSON.stringify(b) : undefined });
    let d = {}; try { d = await r.json() } catch (e) { }
    if (!r.ok) throw new Error(d.error || 'Terjadi kesalahan');
    return d;
  }

  /* ---- form ---- */
  try { const s = JSON.parse(store.get('wsp_form') || '{}'); ['nm', 'hp', 'al'].forEach(k => { if (s[k]) $(k).value = s[k] }) } catch (e) { }
  $('mode').addEventListener('click', e => {
    const b = e.target.closest('[data-m]'); if (!b) return; mode = b.dataset.m;
    document.querySelectorAll('#mode button').forEach(x => x.classList.toggle('on', x === b));
    $('adr').classList.toggle('hide', mode !== 'Antar'); $('jam').classList.toggle('hide', mode === 'Antar'); update();
  });
  const chips = () => { $('chips').innerHTML = Object.keys(CATS).map(c => `<button class="chip ${c === cat ? 'on' : ''}" data-c="${c}">${CATS[c]}</button>`).join('') };
  $('chips').addEventListener('click', e => { const b = e.target.closest('[data-c]'); if (b) { cat = b.dataset.c; chips(); list() } });
  function list() {
    const l = MENU.filter(m => m.cat === cat);
    $('list').innerHTML = l.length ? l.map(m => `<div class="line"><span class="ic">${esc(m.icon)}</span>
      <span class="n"><b>${esc(m.name)}</b><span class="mut">${esc(m.desc)}</span><br><span class="p">${rp(m.price)}</span></span>
      ${cart[m.id] ? `<span class="qty"><button data-id="${m.id}" data-d="-1" aria-label="Kurangi ${esc(m.name)}">−</button><b>${cart[m.id]}</b><button data-id="${m.id}" data-d="1" aria-label="Tambah ${esc(m.name)}">+</button></span>`
        : `<button class="add" data-id="${m.id}" data-d="1">Tambah</button>`}</div>`).join('') : '<p class="mut">Tidak ada menu di kategori ini.</p>';
  }
  $('list').addEventListener('click', e => {
    const b = e.target.closest('[data-d]'); if (!b) return; const id = b.dataset.id;
    cart[id] = Math.min(20, Math.max(0, (cart[id] || 0) + +b.dataset.d)); if (!cart[id]) delete cart[id]; list(); update();
  });
  const items = () => MENU.filter(m => cart[m.id]);
  function update() {
    const it = items(), t = it.reduce((s, m) => s + m.price * cart[m.id], 0), n = it.reduce((s, m) => s + cart[m.id], 0);
    $('sum').innerHTML = it.length ? it.map(m => `<div class="row"><span>${esc(m.icon)} ${esc(m.name)} ×${cart[m.id]}</span><span>${rp(m.price * cart[m.id])}</span></div>`).join('') : '<p class="mut">Belum ada menu dipilih.</p>';
    renderPays(); $('tot').textContent = rp(t); $('bn').textContent = n + ' item · lihat ringkasan'; $('bt').textContent = rp(t); $('bar').classList.toggle('hide', !n);
    $('info').textContent = mode === 'Antar' ? '🛵 Diantar ke alamatmu. Ongkos kirim dikonfirmasi admin.' : '🏪 Ambil sendiri di warung, tanpa ongkos kirim.';
    store.set('wsp_form', JSON.stringify({ nm: $('nm').value, hp: $('hp').value, al: $('al').value }));
  }
  ['nm', 'hp', 'al'].forEach(i => $(i).addEventListener('input', update));
  $('bar').addEventListener('click', () => $('sum').scrollIntoView({ behavior: 'smooth', block: 'center' }));

  $('pays').addEventListener('click', e => { const b = e.target.closest('[data-p]'); if (b) { pay = b.dataset.p; renderPays() } });
  $('banks').addEventListener('click', e => { const b = e.target.closest('[data-b]'); if (b) { bank = b.dataset.b; renderPays() } });
  $('pinst').addEventListener('click', async e => {
    const c = e.target.closest('[data-claim]');
    if (c) { c.disabled = true; try { await api('POST', '/api/orders/' + c.dataset.claim + '/claim', {}); toast('Terima kasih, admin akan memeriksa pembayaranmu'); track(c.dataset.claim) } catch (x) { toast(x.message); c.disabled = false } return } const b = e.target.closest('[data-copy]'); if (b) navigator.clipboard.writeText(b.dataset.copy).then(() => toast('Nomor rekening disalin')).catch(() => toast('Browser menolak menyalin')) });

  $('send').addEventListener('click', async () => {
    if (busy) return; const err = $('err'); err.classList.add('hide');
    if (!items().length) return showErr('Pilih menu dulu.');
    if (!pay) return showErr('Pilih metode pembayaran.');
    if (pay === 'Transfer' && !bank) return showErr('Pilih bank tujuan transfer.');
    if (!$('nm').value.trim()) return showErr('Nama wajib diisi.');
    if (!$('hp').value.trim()) return showErr('No. HP wajib diisi.');
    if (mode === 'Antar' && !$('al').value.trim()) return showErr('Alamat pengantaran wajib diisi.');
    busy = true; $('send').disabled = true; $('send').textContent = 'Mengirim…';
    try {
      const d = await api('POST', '/api/orders', {
        name: $('nm').value, phone: $('hp').value, type: mode, pay: pay, bank: bank, address: $('al').value, pickup: $('jm').value, note: $('ct').value,
        items: Object.keys(cart).map(id => ({ id: +id, qty: cart[id] }))
      });
      store.set('wsp_code', d.code); cart = {}; $('ct').value = ''; list(); update(); showDone(d.code);
    } catch (e) { showErr(e.message) }
    busy = false; $('send').disabled = false; $('send').textContent = 'Kirim pesanan';
  });
  function showErr(m) { const e = $('err'); e.textContent = m; e.classList.remove('hide') }

  /* ---- status pesanan ---- */
  function showDone(code) {
    $('form').classList.add('hide'); $('bar').classList.add('hide'); $('done').classList.remove('hide');
    $('code').textContent = code; track(code); clearInterval(timer); timer = setInterval(() => track(code), 10000); window.scrollTo(0, 0);
  }
  async function track(code) {
    try {
      const o = await api('GET', '/api/orders/' + code);
      $('status').innerHTML = `<div class="note">${o.status === 'baru' && o.paid ? '✅ Pembayaran diterima, pesanan diproses' : (STATUS[o.status] || esc(o.status))}${o.paid ? ' · 💳 Lunas' : ''}</div>`;
      $('dsum').innerHTML = o.items.map(i => `<div class="row"><span>${esc(i.name)} ×${i.qty}</span><span>${rp(i.price * i.qty)}</span></div>`).join('') + `<div class="row tot"><span>Total</span><span>${rp(o.total)}</span></div>`;
      $('pinst').innerHTML = instr(o);
      if (o.status === 'selesai' || o.status === 'batal') clearInterval(timer);
    } catch (e) { $('status').innerHTML = `<div class="err">${esc(e.message)}</div>`; if (/tidak ditemukan/.test(e.message)) { store.del('wsp_code'); clearInterval(timer) } }
  }
  $('again').addEventListener('click', () => { clearInterval(timer); store.del('wsp_code'); $('done').classList.add('hide'); $('form').classList.remove('hide'); update(); });

  /* ---- pembayaran ---- */
  const PL = { Tunai: ['💵', 'Tunai'], QRIS: ['📱', 'QRIS'], Transfer: ['🏦', 'Transfer bank'] };
  const hint = p => p === 'Tunai' ? (mode === 'Antar' ? 'Bayar ke kurir' : 'Bayar saat ambil') : p === 'QRIS' ? 'Scan setelah pesan' : 'Rekening tampil setelah pesan';
  function renderPays() {
    if (pay && !pays.includes(pay)) pay = '';
    const banks = cfg.banks || [];
    if (pay !== 'Transfer') bank = ''; else if (!banks.includes(bank)) bank = banks.length === 1 ? banks[0] : '';
    $('pays').innerHTML = pays.map(p => `<button data-p="${p}" class="${p === pay ? 'on' : ''}">${PL[p][0]} ${PL[p][1]}<small>${hint(p)}</small></button>`).join('');
    $('bankwrap').classList.toggle('hide', pay !== 'Transfer');
    $('banks').innerHTML = banks.map(b => `<button data-b="${esc(b)}" class="${b === bank ? 'on' : ''}">🏦 ${esc(b)}</button>`).join('');
    $('pnote').textContent = !pay ? 'Pilih salah satu metode pembayaran.' : 'Bayar dulu setelah menekan Kirim pesanan. Pesanan baru diproses setelah pembayaranmu diterima dan diverifikasi admin (otomatis batal jika tidak dibayar dalam 60 menit).';
    $('pnote').classList.toggle('hide', pay === 'Tunai');
  }
  function instr(o) {
    const i = o.instructions; if (!i) return '';
    const pre = i.method !== 'Tunai' && !o.paid;
    let h = `<h2>${pre ? 'Bayar dulu' : 'Cara bayar'}</h2><div class="card">`;
    if (pre) h += '<div class="err">Pesananmu baru diproses setelah pembayaran diterima dan diverifikasi admin.</div>';
    h += `<div class="row"><span>Total yang dibayar</span><b>${rp(o.total)}</b></div>`;
    if (i.method === 'Transfer') h += i.banks.map(b => `<div class="row"><span><b>${esc(b.bank)}</b> ${esc(b.number)}<br><span class="mut">a.n. ${esc(b.holder)}</span></span><button class="btn s g" data-copy="${esc(b.number)}">Salin</button></div>`).join('');
    else if (i.method === 'QRIS') h += i.qris ? `<p class="mut">Scan barcode QRIS berikut dengan aplikasi bank / e-wallet.</p><img class="qris" src="${esc(i.qris)}" alt="QRIS Warung Soekardjo">` : '<p class="mut">QRIS belum tersedia, hubungi admin.</p>';
    else h += `<p class="mut">${esc(i.note)}</p>`;
    if (pre) h += o.claimed ? '<div class="note">✋ Menunggu admin memverifikasi pembayaranmu…</div>' : `<button class="btn" data-claim="${esc(o.code)}">Saya sudah bayar</button>`;
    if (i.method !== 'Tunai' && /^\d{8,15}$/.test(cfg.wa || '')) h += `<a class="btn g" target="_blank" rel="noopener noreferrer" href="https://wa.me/${cfg.wa}?text=${encodeURIComponent('Bukti pembayaran pesanan ' + o.code + ' (' + rp(o.total) + ')')}">Kirim bukti bayar via WhatsApp</a>`;
    return h + '</div>';
  }

  /* ---- mulai ---- */
  chips();
  api('GET', '/api/config').then(c => { cfg = c; pays = c.payments || []; if (pays.length === 1) pay = pays[0]; renderPays() }).catch(() => { });
  api('GET', '/api/menu').then(m => { MENU = m; list(); update() }).catch(() => { $('list').innerHTML = '<div class="err">Menu gagal dimuat. Muat ulang halaman.</div>' });
  const saved = store.get('wsp_code'); if (saved && /^[A-Z2-9]{10}$/.test(saved)) showDone(saved);
  update();
})();
