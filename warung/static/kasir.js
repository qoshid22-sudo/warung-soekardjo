(() => {
  const $ = id => document.getElementById(id);
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const rp = n => 'Rp ' + Number(n).toLocaleString('id-ID');
  const CATS = { paket: '📦 Paket', ayam: '🍗 Ayam', sayur: '🥬 Sayur', nasi: '🍚 Nasi', minuman: '🧋 Minuman' };
  let csrf = '', tab = 'pesanan', filter = 'aktif', armed = null, poll = null, lastMax = null, menu = [];

  const toast = m => { const t = $('toast'); t.textContent = m; t.classList.add('show'); clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove('show'), 2400) };
  function arm(k, fn) { if (armed === k) { armed = null; fn() } else { armed = k; toast('Tekan sekali lagi untuk konfirmasi'); setTimeout(() => { if (armed === k) armed = null }, 3000) } }
  const hm = t => new Date(t * 1000).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
  const waNum = p => { let d = String(p).replace(/\D/g, ''); if (d[0] === '0') d = '62' + d.slice(1); return d };

  async function api(m, u, b) {
    const h = {}; if (b) h['Content-Type'] = 'application/json'; if (csrf) h['X-CSRF-Token'] = csrf;
    const r = await fetch(u, { method: m, headers: h, body: b ? JSON.stringify(b) : undefined, credentials: 'same-origin' });
    let d = {}; try { d = await r.json() } catch (e) { }
    if (r.status === 401 && u !== '/api/login') { showLogin(); throw new Error('Sesi berakhir, silakan login lagi') }
    if (!r.ok) throw new Error(d.error || 'Terjadi kesalahan');
    return d;
  }
  const fail = e => toast(e.message);

  /* ---- login ---- */
  function showLogin() { clearInterval(poll); csrf = ''; $('app').classList.add('hide'); $('login').classList.remove('hide'); $('pw').focus() }
  function showApp() { $('login').classList.add('hide'); $('app').classList.remove('hide'); show(tab); clearInterval(poll); poll = setInterval(() => { if (!document.hidden && tab === 'pesanan') loadOrders() }, 8000) }
  $('lf').addEventListener('submit', async e => {
    e.preventDefault(); const er = $('lerr'); er.classList.add('hide');
    try { const d = await api('POST', '/api/login', { password: $('pw').value }); csrf = d.csrf; $('pw').value = ''; showApp() }
    catch (x) { er.textContent = x.message; er.classList.remove('hide') }
  });
  $('logout').addEventListener('click', async () => { try { await api('POST', '/api/admin/logout', {}) } catch (e) { } showLogin() });
  $('pf').addEventListener('submit', async e => {
    e.preventDefault();
    try { await api('POST', '/api/admin/password', { old: $('po').value, new: $('pn').value }); $('po').value = $('pn').value = ''; toast('Password diganti') } catch (x) { fail(x) }
  });

  /* ---- tab ---- */
  $('tabs').addEventListener('click', e => { const b = e.target.closest('[data-t]'); if (!b) return; tab = b.dataset.t; document.querySelectorAll('#tabs button').forEach(x => x.classList.toggle('on', x === b)); show(tab) });
  function show(t) {
    document.querySelectorAll('.pg').forEach(p => p.classList.toggle('hide', p.id !== 'p-' + t));
    if (t === 'pesanan') loadOrders(); if (t === 'menu') loadMenu(); if (t === 'laporan') loadReport();
  }

  /* ---- pesanan ---- */
  $('ofil').addEventListener('click', e => { const b = e.target.closest('[data-f]'); if (!b) return; filter = b.dataset.f; document.querySelectorAll('#ofil .chip').forEach(x => x.classList.toggle('on', x === b)); loadOrders() });
  async function loadOrders() {
    try {
      const l = await api('GET', '/api/admin/orders?status=' + filter);
      const mx = l.reduce((m, o) => Math.max(m, o.id), 0);
      if (lastMax !== null && mx > lastMax && filter === 'aktif') toast('🔔 Ada pesanan baru!');
      if (filter === 'aktif') lastMax = Math.max(lastMax || 0, mx);
      $('olist').innerHTML = l.length ? l.map(card).join('') : '<div class="empty">Tidak ada pesanan di sini.</div>';
    } catch (e) { if (!/login/.test(e.message)) fail(e) }
  }
  function card(o) {
    const open = o.status === 'menunggu' || o.status === 'baru' || o.status === 'siap';
    return `<div class="card ord ${o.status}" data-id="${o.id}">
      <div class="oh"><b>#${o.id} · ${esc(o.name)}</b><span class="mut">${hm(o.created)} · ${esc(o.type)}${o.type === 'Ambil sendiri' ? ' · ' + esc(o.pickup) : ''}</span></div>
      <div class="mut">💳 Pilihan bayar: ${esc(o.pay)}${o.bank ? ' · ' + esc(o.bank) : ''}${o.claimed && !o.paid ? ' · ✋ <b>pelanggan mengaku sudah bayar</b>' : ''}<br>📞 ${esc(o.phone)}${o.address ? '<br>📍 ' + esc(o.address) : ''}</div>
      <div>${o.items.map(i => `${esc(i.name)} ×${i.qty}`).join(', ')}</div>
      ${o.note ? `<div class="mut">📝 ${esc(o.note)}</div>` : ''}
      <div class="oh"><b>${rp(o.total)}</b><span><span class="tag t-${o.status}">${esc(o.status)}</span><span class="tag ${o.paid ? 't-lunas' : 't-belum'}">${o.paid ? 'Lunas · ' + esc(o.method) : 'Belum bayar'}</span></span></div>
      <div class="acts">
        ${open && !o.paid ? ['Tunai', 'QRIS', 'Transfer'].map(m => `<button class="btn s ok" data-a="pay" data-m="${m}">Lunas ${m}${m === o.pay ? ' ★' : ''}</button>`).join('') : ''}
        ${o.status === 'baru' ? '<button class="btn s bl" data-a="siap">Tandai siap</button>' : ''}
        ${o.status === 'siap' ? '<button class="btn s bl" data-a="selesai">Selesai</button>' : ''}
        <a class="btn s g" target="_blank" rel="noopener noreferrer" href="https://wa.me/${waNum(o.phone)}">WhatsApp</a>
        ${open ? '<button class="btn s g" data-a="batal">Batalkan</button>' : ''}
      </div></div>`;
  }
  $('olist').addEventListener('click', async e => {
    const b = e.target.closest('[data-a]'); if (!b) return; const id = b.closest('[data-id]').dataset.id, a = b.dataset.a;
    const send = body => api('PATCH', '/api/admin/orders/' + id, body).then(loadOrders).catch(fail);
    if (a === 'pay') send({ paid: true, method: b.dataset.m });
    else if (a === 'batal') arm('b' + id, () => send({ status: 'batal' }));
    else send({ status: a });
  });

  /* ---- menu ---- */
  $('nc').innerHTML = Object.keys(CATS).map(c => `<option value="${c}">${CATS[c]}</option>`).join('');
  async function loadMenu() {
    try {
      menu = await api('GET', '/api/admin/menu');
      $('mlist').innerHTML = menu.map(m => `<div class="mrow" data-id="${m.id}">
        <input data-k="icon" value="${esc(m.icon)}" maxlength="8" aria-label="Ikon"><input data-k="name" value="${esc(m.name)}" maxlength="40" aria-label="Nama">
        <input data-k="price" type="number" min="0" value="${m.price}" aria-label="Harga">
        <select data-k="cat" aria-label="Kategori">${Object.keys(CATS).map(c => `<option value="${c}" ${c === m.cat ? 'selected' : ''}>${CATS[c]}</option>`).join('')}</select>
        <span class="x"><button class="btn s ${m.active ? 'ok' : 'g'}" data-a="tog">${m.active ? 'Tersedia' : 'Habis'}</button><button class="btn s g" data-a="del">Hapus</button></span></div>`).join('');
    } catch (e) { fail(e) }
  }
  const rowData = r => { const g = k => r.querySelector(`[data-k="${k}"]`).value; const m = menu.find(x => x.id == r.dataset.id); return { name: g('name'), cat: g('cat'), price: parseInt(g('price'), 10), icon: g('icon'), desc: m.desc, active: !!m.active } };
  $('mlist').addEventListener('change', async e => {
    const r = e.target.closest('.mrow'); if (!r || !e.target.dataset.k) return;
    try { await api('PUT', '/api/admin/menu/' + r.dataset.id, rowData(r)); toast('Tersimpan'); loadMenu() } catch (x) { fail(x) }
  });
  $('mlist').addEventListener('click', async e => {
    const b = e.target.closest('[data-a]'); if (!b) return; const r = b.closest('.mrow'), id = r.dataset.id;
    try {
      if (b.dataset.a === 'tog') { const d = rowData(r); d.active = !d.active; await api('PUT', '/api/admin/menu/' + id, d); loadMenu() }
      else arm('d' + id, async () => { try { await api('DELETE', '/api/admin/menu/' + id); loadMenu() } catch (x) { fail(x) } });
    } catch (x) { fail(x) }
  });
  $('add').addEventListener('click', async () => {
    try {
      await api('POST', '/api/admin/menu', { name: $('nn').value, cat: $('nc').value, price: parseInt($('np').value, 10), icon: $('nic').value || '🍽️', desc: '', active: true });
      $('nn').value = $('np').value = ''; toast('Menu ditambahkan'); loadMenu();
    } catch (x) { fail(x) }
  });

  /* ---- laporan ---- */
  async function loadReport() {
    try {
      const r = await api('GET', '/api/admin/report'); const mx = r.top.length ? r.top[0].q : 1;
      $('stats').innerHTML = `<div class="card stat"><b>${rp(r.paid)}</b><span class="mut">Pemasukan (lunas)</span></div><div class="card stat"><b>${r.count}</b><span class="mut">Pesanan</span></div><div class="card stat"><b>${rp(r.unpaid)}</b><span class="mut">Belum dibayar</span></div>`;
      $('top').innerHTML = r.top.length ? r.top.map(t => `<div class="row"><span>${esc(t.name)}</span><b>${t.q}</b></div>`).join('') : '<p class="mut">Belum ada penjualan.</p>';
      $('meth').innerHTML = r.methods.length ? r.methods.map(t => `<div class="row"><span>${esc(t.method)}</span><b>${rp(t.t)}</b></div>`).join('') : '<p class="mut">Belum ada pembayaran.</p>';
    } catch (e) { fail(e) }
  }

  /* ---- mulai ---- */
  api('GET', '/api/admin/me').then(d => { csrf = d.csrf; showApp() }).catch(() => { });
})();
