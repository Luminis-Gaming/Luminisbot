// Luminis auction house (auctionhouse/web): the search page and the item page. Data comes in #ah-data; search
// results from /ah/api/search; item tooltips from /ah/tooltip (Wowhead, sanitized on the server).
(() => {
const dataEl = document.getElementById('ah-data');
if (!dataEl) return;
const D = JSON.parse(dataEl.textContent);
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const QUALITIES = ['POOR', 'COMMON', 'UNCOMMON', 'RARE', 'EPIC', 'LEGENDARY', 'ARTIFACT', 'HEIRLOOM'];
const QNAME = ['Poor', 'Common', 'Uncommon', 'Rare', 'Epic', 'Legendary', 'Artifact', 'Heirloom'];
const LANG = {en: 'English', de: 'German', fr: 'French', es: 'Spanish', ru: 'Russian', it: 'Italian', pt: 'Portuguese'};
const POP = {FULL: 'Full', HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low', NEW_PLAYERS: 'New players', RECOMMENDED: 'Recommended', LOCKED: 'Locked'};
const SHORT = {'Critical Strike': 'Crit', Haste: 'Haste', Mastery: 'Mastery', Versatility: 'Vers'};
const PAIRS = ['Critical Strike/Haste', 'Critical Strike/Mastery', 'Critical Strike/Versatility', 'Haste/Mastery', 'Haste/Versatility', 'Mastery/Versatility'];
const TERTIARY = ['Speed', 'Leech', 'Avoidance', 'Indestructible'];
const TIME_LEFT = ['Under 30 min', '30 min – 2 h', '2 – 12 h', '12 – 48 h'];
const AH_CUT = 0.95;
const PRICE_CAP = 9990000 * 10000;  // at or near the 9,999,999g maximum: a lottery ticket, not a price
const store = {get(k) { try { return localStorage.getItem(k); } catch { return null; } },
               set(k, v) { try { localStorage.setItem(k, v); } catch {} }};

// ---------- realms ----------
const realmGroups = D.realms || {};
let myRealm = +(store.get('ah-my-realm') || 0) || null;
if (myRealm && !realmGroups[myRealm]) myRealm = null;
const myRealmName = () => store.get('ah-my-realm-name') || '';
// A realm group goes by its first realm - or by yours, once you've picked it ("Frostwhisper +5", not "Genjuros +5")
const groupName = cr => {
  const g = realmGroups[cr];
  if (!g) return `Realm ${cr}`;
  return (+cr === myRealm && g.names.includes(myRealmName())) ? myRealmName() : g.names[0];
};
const groupMore = cr => (realmGroups[cr] ? realmGroups[cr].names.length - 1 : 0);
const groupOthers = cr => (realmGroups[cr] ? realmGroups[cr].names.filter(n => n !== groupName(cr)) : []);
const realmList = [];
for (const [cr, g] of Object.entries(realmGroups)) for (const n of g.names) realmList.push({name: n, cr: +cr});
realmList.sort((a, b) => a.name.localeCompare(b.name));

// ---------- formatting ----------
const qkey = q => QUALITIES[q] || 'COMMON';
function coins(c) {
  c = Math.round(c);
  const g = Math.floor(c / 10000), s = Math.floor(c / 100) % 100, cp = c % 100;
  let out = '';
  if (g) out += `<span class="g">${g.toLocaleString('en-GB')}<i>g</i></span>`;
  if (g < 1000 && s) out += `<span class="s">${s}<i>s</i></span>`;
  if (g < 10 && cp) out += `<span class="c">${cp}<i>c</i></span>`;
  return `<span class="coin">${out || '<span class="c">0<i>c</i></span>'}</span>`;
}
const gold = c => {
  const g = c / 10000;
  if (g >= 1e6) return (g / 1e6).toFixed(g >= 1e7 ? 0 : 2).replace(/\.?0+$/, '') + 'M g';
  if (g >= 1e4) return Math.round(g / 1e3).toLocaleString('en-GB') + 'k g';
  if (g >= 1) return Math.round(g).toLocaleString('en-GB') + ' g';
  return 'under 1 g';
};
const pct = x => (x > 0 ? '+' : '') + Math.round(x * 100) + '%';
const realmLabel = cr => `${esc(groupName(cr))}${groupMore(cr) ? ` <small>+${groupMore(cr)}</small>` : ''}`;
const icon = (it, cls = '', tt = '', focusable = true) => `<span class="item-icon ${cls} q-${qkey(it.q)}" ${tt ? `data-tt="${esc(tt)}"${focusable ? ' tabindex="0"' : ''}` : ''}>${it.icon
  ? `<img src="${esc(it.icon)}" alt="" width="56" height="56" loading="lazy">` : `<span class="fallback">${esc((it.name || '?')[0])}</span>`}</span>`;
const ttAttr = (tt, note = '') => `data-tt="${esc(tt)}"${note ? ` data-tt-note="${esc(note)}"` : ''}`;
// A small icon that shows the tooltip of one roll: the only thing on a row you hover for it. Inside a button
// (the roll picker) it can't take focus itself; everywhere else the keyboard can reach it too.
const tipIcon = (it, tt, note = '', focusable = true) => `<span class="item-icon sm q-${qkey(it.q)}" ${ttAttr(tt, note)}${
  focusable ? ` tabindex="0" aria-label="${esc(it.name)} tooltip"` : ''}>${it.icon
  ? `<img src="${esc(it.icon)}" alt="" width="24" height="24" loading="lazy">` : `<span class="fallback">${esc((it.name || '?')[0])}</span>`}</span>`;

// ---------- chart tooltip ----------
const tip = $('#tip');
function showTip(html, x, y) {
  tip.innerHTML = html; tip.hidden = false;
  const r = tip.getBoundingClientRect();
  tip.style.left = Math.max(8, Math.min(window.innerWidth - r.width - 8, x + 14)) + 'px';
  tip.style.top = (y - r.height - 12 < 8 ? y + 16 : y - r.height - 12) + 'px';
}
const hideTip = () => { tip.hidden = true; };

// ---------- item tooltip ----------
// Hovering an item icon (data-tt="itemId|query"), or reaching it with the keyboard, shows the game's tooltip for
// exactly that roll, fetched the first time and then kept. It goes as soon as the pointer is off the icon. Touch: the
// first tap shows it, a second tap does what the icon's row does.
const itemtip = $('#itemtip');
const tips = new Map();
let ttEl = null, ttX = 0, ttY = 0;
const loadTip = key => {
  if (!tips.has(key)) {
    const [id, q] = key.split('|');
    tips.set(key, fetch(`/ah/tooltip/${id}${q ? '?' + q : ''}`).then(r => (r.ok ? r.json() : null)).catch(() => null)
      .then(data => { tips.set(key, data); return data; }));
  }
  return tips.get(key);
};
function placeItemTip() {
  const w = itemtip.offsetWidth, h = itemtip.offsetHeight;
  let x = ttX + 18, y = ttY + 18;
  if (x + w > innerWidth - 8) x = Math.max(8, ttX - w - 18);
  if (y + h > innerHeight - 8) y = Math.max(8, innerHeight - h - 8);
  itemtip.style.left = x + 'px'; itemtip.style.top = y + 'px';
}
function renderItemTip(el, data) {
  if (ttEl !== el) return;
  if (!data) { itemtip.hidden = true; return; }
  const note = el.dataset.ttNote;
  itemtip.className = data.quality != null ? `q-${qkey(data.quality)}` : '';
  itemtip.innerHTML = `${data.icon ? `<span class="it-icon"><img src="${esc(data.icon)}" alt=""></span>` : ''}
    <div class="it-body">${note ? `<div class="it-note">${note}</div>` : ''}${data.html}</div>`;  // html: rebuilt from an allow-list on the server
  itemtip.hidden = false;
  placeItemTip();
}
function showItemTip(el) {
  ttEl = el;
  const data = loadTip(el.dataset.tt);
  if (data instanceof Promise) {
    itemtip.className = '';
    itemtip.innerHTML = '<div class="it-body"><span class="muted">Loading tooltip…</span></div>';
    itemtip.hidden = false; placeItemTip();
    data.then(d => renderItemTip(el, d));
  } else renderItemTip(el, data);
}
function hideItemTip() { itemtip.hidden = true; ttEl = null; }
let touchTap = false;
document.addEventListener('pointerdown', e => { touchTap = e.pointerType === 'touch'; });
document.addEventListener('pointermove', e => {
  if (e.pointerType === 'touch') return;
  ttX = e.clientX; ttY = e.clientY;
  const el = e.target.closest && e.target.closest('[data-tt]');
  if (el) { if (el !== ttEl) showItemTip(el); else if (!itemtip.hidden) placeItemTip(); }
  else if (ttEl) hideItemTip();
});
document.documentElement.addEventListener('pointerleave', () => hideItemTip());
window.addEventListener('blur', () => hideItemTip());
document.addEventListener('focusin', e => {
  const el = e.target.closest && e.target.closest('[data-tt]');
  if (!el || !el.matches(':focus-visible')) return;  // keyboard focus only: a click mustn't leave a tooltip behind
  const r = el.getBoundingClientRect(); ttX = r.right; ttY = r.top;
  showItemTip(el);
});
document.addEventListener('focusout', e => { if (ttEl && ttEl.contains(e.target)) hideItemTip(); });
document.addEventListener('click', e => {
  if (!touchTap) return;
  const el = e.target.closest && e.target.closest('[data-tt]');
  if (el && el !== ttEl) {
    e.preventDefault(); e.stopPropagation();
    const r = el.getBoundingClientRect(); ttX = r.left; ttY = r.bottom;
    showItemTip(el);
  } else if (!el) hideItemTip();
}, true);
document.addEventListener('scroll', hideItemTip, true);
document.addEventListener('keydown', e => { if (e.key === 'Escape') hideItemTip(); });

// ---------- market bar ----------
(() => {
  const el = $('#market-stats'), snap = D.snapshot || {};
  if (!el) return;
  if (!snap.swept_at) { el.innerHTML = '<span>Collecting the first snapshot of every EU auction house…</span>'; return; }
  const when = new Date(snap.swept_at).toLocaleString('en-GB', {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
  el.innerHTML = `<span><span class="live-dot" aria-hidden="true"></span>Updated <b>${when}</b></span>
    <span><b>${snap.groups}</b> realm groups</span><span><b>${(snap.listings || 0).toLocaleString('en-GB')}</b> listings</span>
    <span><b>${(snap.items || 0).toLocaleString('en-GB')}</b> different items</span>`;
})();

const rollText = r => {
  const parts = [];
  if (r.sec) parts.push(r.sec.split('/').map(s => SHORT[s] || s).join(' / '));
  if (r.ter) parts.push(r.ter);
  if (r.sock) parts.push('Socket');
  return parts.join(' · ');
};
const rollQuery = r => {
  const p = new URLSearchParams();
  if (r.sec) p.set('sec', r.sec);
  if (r.ter) p.set('ter', r.ter);
  if (r.sock) p.set('sock', 'yes');
  if (r.ilvl) p.set('ilvl', r.ilvl);
  return p.toString();
};

if (D.page === 'search') initSearch();
else if (D.page === 'item') initItem();

// =====================================================================================================================
// Search page
// =====================================================================================================================
function initSearch() {
  const form = $('#search-form');
  const els = {q: $('#q'), realm: $('#realm'), ilvlMin: $('#ilvl-min'), ilvlMax: $('#ilvl-max'), reqMin: $('#req-min'),
    reqMax: $('#req-max'), qMin: $('#q-min'), qMax: $('#q-max'), exp: $('#exp'), sec: $('#f-sec'), ter: $('#f-ter'),
    sock: $('#f-sock'), below: $('#below-vendor'), oos: $('#out-of-stock'), medCol: $('#median-col')};
  els.realm.innerHTML = '<option value="">All EU realms</option>' + realmList.map(r => `<option value="${r.cr}|${esc(r.name)}">${esc(r.name)}</option>`).join('');
  const qOpts = QNAME.slice(0, 6).map((q, i) => `<option value="${i}">${q}</option>`).join('');
  els.qMin.innerHTML = qOpts; els.qMax.innerHTML = qOpts; els.qMax.value = '5';
  els.exp.innerHTML = '<option value="">All expansions</option>' + (D.expansions || []).map((n, i) => `<option value="${i}">${esc(n)}</option>`).reverse().join('');
  els.sec.innerHTML = '<option value="">Any</option>' + PAIRS.map(p => `<option value="${p}">${p.replace('/', ' / ')}</option>`).join('');
  els.ter.innerHTML = '<option value="">Any</option><option value="any">Any tertiary stat</option><option value="none">None</option>'
    + TERTIARY.map(t => `<option value="${t}">${t}</option>`).join('');

  // first view: the items listed on the most realms - what actually trades (one realm's lottery ask isn't news)
  const state = {cat: null, sub: null, sort: 'realms', dir: 'desc', offset: 0, rows: [], total: 0};
  // the address keeps the search, so it can be shared and Back returns to it
  const url = new URLSearchParams(location.search);
  const setVal = (el, v) => { if (v != null) el.value = v; };
  setVal(els.q, url.get('q')); setVal(els.ilvlMin, url.get('ilvl_min')); setVal(els.ilvlMax, url.get('ilvl_max'));
  setVal(els.reqMin, url.get('req_min')); setVal(els.reqMax, url.get('req_max')); setVal(els.qMin, url.get('q_min'));
  setVal(els.qMax, url.get('q_max')); setVal(els.exp, url.get('exp')); setVal(els.sec, url.get('sec')); setVal(els.ter, url.get('ter'));
  els.sock.checked = url.get('sock') === '1'; els.below.checked = url.get('below') === '1'; els.oos.checked = url.get('oos') === '1';
  if (url.get('realm')) {
    const opt = [...els.realm.options].find(o => o.value.split('|')[0] === url.get('realm'));
    if (opt) els.realm.value = opt.value;
  } else if (myRealm && url.get('mine') === '1') {
    const opt = [...els.realm.options].find(o => o.value === `${myRealm}|${myRealmName()}`);
    if (opt) els.realm.value = opt.value;
  }
  state.cat = url.get('cat'); state.sub = url.get('sub');
  if (url.get('sort')) { state.sort = url.get('sort'); state.dir = url.get('dir') === 'asc' ? 'asc' : 'desc'; }

  function params() {
    const p = new URLSearchParams();
    const add = (k, v) => { if (v != null && v !== '') p.set(k, v); };
    add('q', els.q.value.trim()); add('realm', els.realm.value.split('|')[0]);
    add('cat', state.cat); add('sub', state.sub);
    add('ilvl_min', els.ilvlMin.value); add('ilvl_max', els.ilvlMax.value); add('req_min', els.reqMin.value); add('req_max', els.reqMax.value);
    if (els.qMin.value !== '0') add('q_min', els.qMin.value);
    if (els.qMax.value !== '5') add('q_max', els.qMax.value);
    add('exp', els.exp.value); add('sec', els.sec.value); add('ter', els.ter.value);
    if (els.sock.checked) add('sock', '1');
    if (els.below.checked) add('below', '1');
    if (els.oos.checked) add('oos', '1');
    if (state.sort !== 'realms' || state.dir !== 'desc') { add('sort', state.sort); add('dir', state.dir); }
    return p;
  }
  const statFilter = () => !!(els.sec.value || els.ter.value || els.sock.checked);

  function renderCats() {
    const cats = D.categories || [];
    const btn = (label, n, cat, sub, pressed, cls = '') =>
      `<li><button type="button" class="cat-btn ${cls}" data-cat="${cat ?? ''}" data-sub="${sub ?? ''}" aria-pressed="${pressed}">
        <span>${esc(label)}</span><span class="count">${n.toLocaleString('en-GB')}</span></button></li>`;
    let html = btn('All categories', cats.reduce((a, c) => a + c.n, 0), null, null, !state.cat);
    for (const c of cats) {
      html += btn(c.name, c.n, c.id, null, String(state.cat) === String(c.id) && !state.sub);
      if (String(state.cat) === String(c.id)) for (const s of c.subs)
        html += btn(s.name, s.n, c.id, s.id, String(state.sub) === String(s.id), 'cat-sub');
    }
    $('#cats').innerHTML = html;
  }

  function renderOpps() {
    const opps = D.opps || [];
    $('#opps-section').hidden = !opps.length;
    $('#opps').innerHTML = opps.map(o => `<a class="opp" href="/ah/item/${o.item.id}${o.roll ? '?' + rollQuery(o.roll) : ''}">
      ${icon(o.item, '', `${o.item.id}|${o.roll ? o.roll.tooltip : ''}`, false)}<span class="opp-name qtext q-${qkey(o.item.q)}">${esc(o.item.name)}</span>
      <span class="item-sub">${o.roll && rollText(o.roll) ? esc(rollText(o.roll)) + ' · ilvl ' + o.roll.ilvl : esc(o.item.sub)} · ${o.realms} realms</span>
      <span class="opp-route"><span>Buy on ${esc(groupName(o.buy_cr))}</span> ${coins(o.buy)}
        <span class="arrow" aria-hidden="true">→</span><span>sell on ${esc(groupName(o.sell_cr))}</span> ${coins(o.sell)}
        <span class="opp-gain">+${gold(o.gain)}</span></span></a>`).join('');
  }

  let pending = 0;
  async function search(append = false) {
    const p = params();
    history.replaceState(null, '', '/ah' + (p.toString() ? '?' + p : ''));
    if (!append) state.offset = 0;
    p.set('offset', state.offset);
    const ticket = ++pending;
    $('#results').classList.add('loading');
    let data;
    try {
      const resp = await fetch('/ah/api/search?' + p);
      data = resp.ok ? await resp.json() : null;
    } catch { data = null; }
    if (ticket !== pending) return;
    $('#results').classList.remove('loading');
    if (!data) { $('#result-count').textContent = 'Search failed. Try again in a moment.'; return; }
    state.rows = append ? state.rows.concat(data.rows) : data.rows;
    state.total = data.total;
    renderResults();
  }

  function renderResults() {
    const realm = els.realm.value ? +els.realm.value.split('|')[0] : null;
    const showMed = els.medCol.checked;
    const cols = realm
      ? [['name', 'Item'], ['ilvl', 'Item level', 'r'], ['req', 'Req.', 'r'], ['here', 'Price here', 'r'], ...(showMed ? [['med', 'EU median', 'r']] : []),
         ['vs', 'vs EU median', 'r'], ['qty', 'Listings here', 'r']]
      : [['name', 'Item'], ['ilvl', 'Item level', 'r'], ['req', 'Req.', 'r'], ['lo', 'Cheapest', 'r'], ...(showMed ? [['med', 'EU median', 'r']] : []),
         ['hi', 'Highest', 'r'], ['realms', 'Realms', 'r'], ['spread', 'Spread', 'r']];
    $('#results thead').innerHTML = '<tr>' + cols.map(([k, label, cls]) =>
      `<th class="${cls || ''}" ${k === state.sort ? `aria-sort="${state.dir === 'asc' ? 'ascending' : 'descending'}"` : ''}>
        <button type="button" class="sort" data-sort="${k}">${label}</button></th>`).join('') + '</tr>';
    const extra = rollQuery({sec: els.sec.value, ter: els.ter.value, sock: els.sock.checked});
    const cell = (r, k) => {
      const spread = r.hi / Math.max(r.lo, 1);
      switch (k) {
        case 'name': return `<td><div class="item-cell">${icon(r, '', `${r.id}|`)}<div><a href="/ah/item/${r.id}${extra ? '?' + extra : ''}" class="qtext q-${qkey(r.q)}">${esc(r.name)}</a>
          ${r.rolls > 1 ? `<span class="rolls-badge">${r.rolls} rolls</span>` : ''}
          <div class="item-sub">${esc(r.sub)}${r.slot ? ' · ' + esc(r.slot) : ''}</div></div></div></td>`;
        case 'ilvl': return `<td class="r num">${r.ilvl_min === r.ilvl_max ? r.ilvl_max : `${r.ilvl_min}–${r.ilvl_max}`}</td>`;
        case 'req': return `<td class="r num">${r.req || '<span class="faint">–</span>'}</td>`;
        case 'lo': return `<td class="r">${coins(r.lo)}<span class="realm-tag">${esc(groupName(r.lo_cr))}</span></td>`;
        case 'hi': return `<td class="r">${coins(r.hi)}<span class="realm-tag">${esc(groupName(r.hi_cr))}</span></td>`;
        case 'med': return `<td class="r">${coins(r.med)}</td>`;
        case 'realms': return `<td class="r num">${r.realms}<span class="faint"> / ${D.snapshot.groups}</span></td>`;
        case 'spread': return `<td class="r"><span class="spread ${spread >= 10 ? 'hot' : ''}">×${spread < 10 ? spread.toFixed(1) : Math.round(spread).toLocaleString('en-GB')}</span></td>`;
        case 'here': return `<td class="r">${r.here != null ? coins(r.here) : '<span class="faint">Not listed</span>'}</td>`;
        case 'vs': {
          if (r.here == null) return '<td class="r faint">–</td>';
          const d = r.here / r.med - 1;
          return `<td class="r num ${d < -0.05 ? 'delta-down' : d > 0.05 ? 'delta-up' : 'muted'}">${pct(d)}</td>`;
        }
        case 'qty': return `<td class="r num">${r.here_n || '<span class="faint">0</span>'}</td>`;
      }
      return '<td></td>';
    };
    $('#results tbody').innerHTML = state.rows.length
      ? state.rows.map(r => `<tr class="link ${realm && r.here == null ? 'dim' : ''}" data-href="/ah/item/${r.id}${extra ? '?' + extra : ''}">${cols.map(c => cell(r, c[0])).join('')}</tr>`).join('')
      : `<tr><td colspan="${cols.length}"><div class="empty">${D.snapshot.swept_at ? 'No items match these filters. Clear a filter or pick another category.'
          : 'The first snapshot of every EU auction house is still being collected. Check back in a few minutes.'}</div></td></tr>`;
    $('#result-count').textContent = `${state.total.toLocaleString('en-GB')} item${state.total === 1 ? '' : 's'}`
      + (statFilter() ? ' · only items that roll random stats' : '');
    $('#result-mode').textContent = realm
      ? `Prices on ${els.realm.value.split('|')[1]}${groupMore(realm) ? ` (shares its auction house with ${groupMore(realm)} connected realm${groupMore(realm) === 1 ? '' : 's'})` : ''}`
      : 'Comparing all EU realms';
    $('#more').hidden = state.rows.length >= state.total;
  }

  let debounce;
  form.addEventListener('input', e => {
    clearTimeout(debounce);
    if (e.target === els.medCol) { renderResults(); return; }
    debounce = setTimeout(() => search(), e.target === els.q || e.target.type === 'number' ? 300 : 0);
  });
  form.addEventListener('submit', e => { e.preventDefault(); search(); });
  form.addEventListener('reset', () => setTimeout(() => { state.cat = state.sub = null; renderCats(); search(); }));
  $('#results thead').addEventListener('click', e => {
    const b = e.target.closest('[data-sort]'); if (!b) return;
    const k = b.dataset.sort;
    if (state.sort === k) state.dir = state.dir === 'asc' ? 'desc' : 'asc';
    else { state.sort = k; state.dir = ['name', 'here', 'vs'].includes(k) ? 'asc' : 'desc'; }
    search();
  });
  $('#results tbody').addEventListener('click', e => {
    const row = e.target.closest('tr[data-href]');
    if (!row || e.target.closest('a')) return;
    location.href = row.dataset.href;
  });
  $('#cats').addEventListener('click', e => {
    const b = e.target.closest('.cat-btn'); if (!b) return;
    state.cat = b.dataset.cat || null; state.sub = b.dataset.sub || null;
    renderCats(); search();
  });
  $('#more').addEventListener('click', () => { state.offset = state.rows.length; search(true); });
  if (window.matchMedia('(max-width: 860px)').matches) $('#rail').open = false;
  renderCats(); renderOpps(); search();
}

// =====================================================================================================================
// Item page
// =====================================================================================================================
function initItem() {
  const raw = D.item;
  const it = {...raw, variants: (D.variants || []).map((v, i) => ({...v, i, tt: `${raw.id}|${v.q || ''}`}))};
  it.hasVariants = it.variants.length > 1 || it.variants.some(v => v.sec || v.ter || v.sock);
  const listings = D.listings || [];

  const url = new URLSearchParams(location.search);
  let rollFilter = {sec: url.get('sec') || '', ter: url.get('ter') || '', sock: url.get('sock') || '', ilvl: url.get('ilvl') ? +url.get('ilvl') : null};
  let tableSort = {key: 'lo', dir: -1};
  let listRealm = null;

  const pairLabel = sec => sec ? sec.split('/').map(s => SHORT[s] || s).join(' / ') : '';
  const rollLabel = v => {
    if (!it.hasVariants) return '';
    const parts = [];
    if (v.sec) parts.push(pairLabel(v.sec));
    if (v.ter) parts.push(v.ter);
    if (v.sock) parts.push('Socket');
    return `<span class="roll">${parts.length ? `<b>${esc(parts.join(' · '))}</b>` : 'No extra stats'} · ilvl ${v.ilvl}</span>`;
  };
  const quantile = (sorted, p) => {
    const i = (sorted.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
  };
  const matches = (v, f) => (!f.sec || v.sec === f.sec)
    && (!f.ter || (f.ter === 'none' ? !v.ter : f.ter === 'any' ? !!v.ter : v.ter === f.ter))
    && (!f.sock || (f.sock === 'yes') === !!v.sock)
    && (f.ilvl == null || v.ilvl === f.ilvl);

  // The same rules as auctionhouse/prices.py: price walls (one seller or bot posting everywhere) and listings far
  // above the typical price stay visible but are left out of medians, rankings and gaps.
  const sigDigits = n => String(n).replace(/0+$/, '').length;
  const isRound = c => { const g = Math.round(c / 10000); return g < 1000 || sigDigits(g) <= 3 || sigDigits(g + 1) <= 3; };
  const anchored = c => { const g = c / 10000, p = 10 ** (Math.floor(Math.log10(g)) - 1), a = Math.ceil(g / p) * p; return a - g >= 0 && a - g <= Math.max(a * 0.0001, 1); };
  (function findWalls() {
    const seen = {}, cheapest = {};
    for (const v of it.variants) for (const [cr, lo] of v.realms) {
      seen[lo] = (seen[lo] || 0) + 1;
      cheapest[cr] = Math.min(cheapest[cr] ?? Infinity, lo);
    }
    it.wallCount = {};
    const prices = Object.keys(seen).map(Number).sort((a, b) => a - b);
    let cluster = [];
    const close = () => {
      const count = cluster.reduce((a, p) => a + seen[p], 0);
      const odd = cluster.reduce((a, p) => a + (isRound(p) || anchored(p) ? 0 : seen[p]), 0);
      if (count >= 3 && odd * 2 >= count) for (const p of cluster) it.wallCount[p] = count;
      cluster = [];
    };
    for (const p of prices) {
      if (cluster.length && p > cluster[cluster.length - 1] * 1.003) close();
      cluster.push(p);
    }
    if (cluster.length) close();
    for (const [p, c] of Object.entries(seen)) if (+p >= PRICE_CAP) it.wallCount[p] = c;
    const clean = Object.values(cheapest).filter(p => !it.wallCount[p]).sort((a, b) => a - b);
    it.ref = clean.length ? quantile(clean, 0.25) : Infinity;
  })();
  function stats(rows) {
    rows = rows.map(r => ({...r, flag: null})).sort((a, b) => a.lo - b.lo);
    if (!rows.length) return null;
    for (const r of rows) if (it.wallCount[r.lo]) { r.flag = 'wall'; r.wallCount = it.wallCount[r.lo]; }
    const rest = rows.filter(r => !r.flag);
    const typical = rest.length >= 5 ? quantile(rest.map(r => r.lo), 0.25) : it.ref;
    for (const r of rest) if (r.lo > typical * 10) r.flag = 'high';
    let sane = rows.filter(r => !r.flag), fellBack = false;
    if (!sane.length) { sane = rows; fellBack = true; }
    const lows = sane.map(r => r.lo);
    const median = quantile(lows, 0.5);  // the gap's sell side: a typical realm, not the priciest
    const target = sane.reduce((best, r) => Math.abs(r.lo - median) < Math.abs(best.lo - median) ? r : best, sane[0]);
    const hi = sane[sane.length - 1];
    return {rows, sane, fellBack, flagged: fellBack ? 0 : rows.length - sane.length, byCr: Object.fromEntries(rows.map(r => [r.cr, r])),
            lo: rows[0], hi, med: quantile(lows, 0.5), n: rows.length, target, gain: target.lo * AH_CUT - rows[0].lo};
  }
  function realmRows(f) {
    const by = {};
    for (const v of it.variants) {
      if (!matches(v, f)) continue;
      for (const [cr, lo, n] of v.realms) {
        const r = by[cr];
        if (!r) by[cr] = {cr, lo, n, v};
        else { r.n += n; if (lo < r.lo) { r.lo = lo; r.v = v; } }
      }
    }
    return Object.values(by);
  }
  const statsFor = f => stats(realmRows(f));
  const variantStats = v => stats(v.realms.map(([cr, lo, n]) => ({cr, lo, n, v})));
  function bestFlip(f) {
    let best = null;
    for (const v of it.variants) {
      if (!matches(v, f) || v.realms.length < 8) continue;
      const s = variantStats(v);
      if (s && !s.fellBack && s.sane.length >= 8 && (!best || s.gain > best.s.gain)) best = {v, s};
    }
    return best;
  }
  const flagText = r => r.flag === 'wall' ? (r.lo >= PRICE_CAP ? 'Listed at the auction house maximum: a lottery ticket, not a price. Not counted in medians or rankings.'
      : `This price (or one within 0.3% of it) is listed ${r.wallCount} times across realms and rolls: one seller or bot posting everywhere. Not counted in medians or rankings.`)
    : r.flag === 'high' ? 'Over 10× the typical price. Not counted in medians or rankings.' : '';
  const ilvlsOf = () => [...new Set(it.variants.map(v => v.ilvl))].sort((a, b) => a - b);
  const pairsOf = () => PAIRS.filter(p => it.variants.some(v => v.sec === p)).concat(it.variants.some(v => !v.sec) ? [''] : []);

  function rankList(rows, color, scaleMax) {
    return `<ol class="rank">${rows.map((r, i) => `<li class="${r.cr === myRealm ? 'you' : ''}">
      <span class="pos">${i + 1}</span>
      ${tipIcon(it, r.v.tt, `<b>${esc(groupName(r.cr))}</b> · cheapest here: ${gold(r.lo)}`)}
      <span class="name">${realmLabel(r.cr)}${r.cr === myRealm ? '<span class="you-tag">YOU</span>' : ''}${rollLabel(r.v)}</span>
      <span class="bar-track"><span class="bar" style="--bar:${color};width:${Math.max(1, r.lo / scaleMax * 100)}%"></span></span>
      <span class="price">${coins(r.lo)}<small>${r.n} listing${r.n === 1 ? '' : 's'}</small></span></li>`).join('')}</ol>`;
  }

  // The roll picker: one ranked list - each secondary-stat pair, cheapest first - that is also the selector.
  function rollsSection() {
    if (!it.hasVariants) return '';
    const f = rollFilter;
    const lvls = ilvlsOf(), pairs = pairsOf();
    const ters = TERTIARY.filter(t => it.variants.some(v => v.ter === t));
    const hasSock = it.variants.some(v => v.sock), noSock = it.variants.some(v => !v.sock);
    const real = s => s && !s.fellBack ? s.sane[0] : null;
    const base = {...f, sec: ''};
    const all = statsFor(base);
    const rows = pairs.map(p => { const s = statsFor({...base, sec: p}); return {p, s, best: real(s)}; }).filter(r => r.s);
    const listed = rows.filter(r => r.best).sort((a, b) => a.best.lo - b.best.lo), walled = rows.filter(r => !r.best);
    const max = Math.max(1, ...listed.map(r => r.best.lo));
    const cheapest = listed.length > 1 ? listed[0].p : null;
    const priced = patch => { const s = statsFor({...f, ...patch}), b = real(s); return b ? `from ${gold(b.lo)}` : s ? 'only bot listings' : 'none listed'; };
    const levelControl = lvls.length < 2 ? '' : lvls.length <= 6
      ? `<div class="seg" role="group" aria-label="Item level"><span class="seg-label">Item level</span>
          ${[[null, 'All'], ...lvls.map(l => [l, String(l)])].map(([l, t]) => `<button type="button" data-ilvl="${l ?? ''}" aria-pressed="${f.ilvl === l}">${t}</button>`).join('')}</div>`
      : `<label class="inline-field"><span>Item level</span><select class="select" id="roll-ilvl">
          <option value="">All (${lvls[0]}–${lvls[lvls.length - 1]})</option>
          ${lvls.map(l => `<option value="${l}" ${f.ilvl === l ? 'selected' : ''}>${l} · ${priced({ilvl: l})}</option>`).join('')}
        </select></label>`;
    const menu = (id, label, options, value) => `<label class="inline-field"><span>${label}</span><select class="select" id="${id}">
      ${options.map(([v, t]) => `<option value="${v}" ${v === value ? 'selected' : ''}>${t}</option>`).join('')}</select></label>`;
    const terMenu = ters.length ? menu('roll-ter', 'Tertiary', [['', 'Any'], ['none', `None · ${priced({ter: 'none'})}`],
      ...ters.map(t => [t, `${t} · ${priced({ter: t})}`])], f.ter) : '';
    const sockMenu = hasSock && noSock ? menu('roll-sock', 'Socket', [['', 'Any'], ['yes', `With socket · ${priced({sock: 'yes'})}`],
      ['no', `No socket · ${priced({sock: 'no'})}`]], f.sock) : '';
    const row = (p, name, sub, s, best, tag) => {
      const note = best ? `${p ? esc(pairLabel(p)) : 'Cheapest roll'} · cheapest on <b>${esc(groupName(best.cr))}</b>` : '';
      return `<button type="button" class="roll-row ${p ? '' : 'all'}" role="radio" aria-checked="${f.sec === p}" data-sec="${esc(p)}">
        <span class="radio" aria-hidden="true"></span>
        ${best ? tipIcon(it, best.v.tt, note, false) : '<span></span>'}
        <span class="roll-name">${name}${tag}<small>${sub}</small></span>
        <span class="roll-price">${best ? `${coins(best.lo)}<span class="roll-track"><span class="roll-bar" style="width:${Math.max(2, best.lo / max * 100).toFixed(1)}%"></span></span>`
          : '<span class="faint small">Only bot listings</span>'}</span>
        <span class="r num muted">${s ? s.n : 0}</span>
        <span class="r">${best ? coins(s.med) : '<span class="faint">–</span>'}</span></button>`;
    };
    const sub = best => best ? `${esc(groupName(best.cr))} · item level ${best.v.ilvl}` : 'Only bot listings';
    const allBest = real(all);
    const active = f.sec || f.ilvl != null || f.ter || f.sock;
    return `<section class="card rolls" aria-labelledby="rolls-title">
      <div class="rolls-head">
        <div><h3 id="rolls-title">Stat rolls</h3>
          <p>This item drops with random stats, and each roll sells for its own price.
          ${cheapest ? `Right now <b>${esc(cheapest.replace('/', ' / '))}</b> is the cheapest to buy.` : ''} Pick a roll and the whole page follows it.</p></div>
        <div class="roll-tools">${levelControl}${terMenu}${sockMenu}</div>
      </div>
      <div class="roll-list" role="radiogroup" aria-label="Secondary stats">
        <div class="roll-row head" aria-hidden="true"><span></span><span></span><span>Secondary stats</span><span>Cheapest in EU</span><span class="r">Realms</span><span class="r">EU median</span></div>
        ${all ? row('', 'Any roll', allBest ? `${it.variants.filter(v => matches(v, base)).length} rolls listed` : 'Only bot listings', all, allBest, '') : ''}
        ${listed.map(r => row(r.p, esc(r.p ? r.p.replace('/', ' / ') : 'No secondary stats'), sub(r.best), r.s, r.best,
          r.p === cheapest ? '<span class="cheap-tag">Cheapest</span>' : '')).join('')}
        ${walled.map(r => row(r.p, esc(r.p ? r.p.replace('/', ' / ') : 'No secondary stats'), 'Only bot listings', r.s, null, '')).join('')}
      </div>
      <div class="roll-foot"><span>Bars compare each roll's cheapest real listing. Bot price walls are left out. Hover an icon for the roll's tooltip.</span>
        ${active ? '<button type="button" class="link-btn" id="roll-clear">Show every roll</button>' : ''}</div>
    </section>`;
  }

  // Every listing on one realm group (yours by default), each compared with the same roll across EU
  function listingsCard(f, S) {
    if (!listings.length) return '';
    const groups = [...new Set(listings.map(l => l[0]))];
    const cr = groups.includes(listRealm) ? listRealm : groups.includes(myRealm) ? myRealm : S.lo.cr;
    const here = listings.filter(l => l[0] === cr).map(([, vi, price, tl]) => ({v: it.variants[vi], price, tl}))
      .filter(l => l.v).sort((a, b) => a.price - b.price);
    const shown = here.filter(l => matches(l.v, f));
    const hidden = here.length - shown.length;
    const cache = new Map();
    const rollStats = v => { if (!cache.has(v)) cache.set(v, variantStats(v)); return cache.get(v); };
    const rows = shown.map(l => {
      const vs = rollStats(l.v);
      const d = vs ? l.price / vs.med - 1 : 0;
      const others = vs ? vs.sane.filter(r => r.cr !== cr) : [];
      const tag = !vs ? '' : others.length && l.price > Math.max(...others.map(r => r.lo)) ? '<span class="flag-tag hi">Priciest in EU</span>'
        : others.length && l.price < Math.min(...others.map(r => r.lo)) ? '<span class="flag-tag lo">Cheapest in EU</span>' : '';
      return `<tr>
        <td><span class="with-icon">${tipIcon(it, l.v.tt, `<b>${esc(groupName(cr))}</b> · ${gold(l.price)}`)}${it.hasVariants ? rollLabel(l.v) : `<span class="roll">Item level ${l.v.ilvl}</span>`}</span></td>
        <td class="r">${coins(l.price)}${tag}</td>
        <td class="r num ${d < -0.05 ? 'delta-down' : d > 0.05 ? 'delta-up' : 'muted'}">${vs ? `${pct(d)}<span class="realm-tag">median ${gold(vs.med)} · ${vs.n} realms</span>` : '–'}</td>
        <td class="muted">${TIME_LEFT[l.tl] || ''}</td></tr>`;
    }).join('');
    const options = groups.sort((a, b) => groupName(a).localeCompare(groupName(b)))
      .map(g => `<option value="${g}" ${g === cr ? 'selected' : ''}>${esc(groupName(g))}${groupMore(g) ? ` +${groupMore(g)}` : ''}${g === myRealm ? ' (your realm)' : ''}</option>`).join('');
    return `<section class="card listings" aria-labelledby="list-title">
      <div class="card-head"><div><h3 id="list-title">Listings on ${esc(groupName(cr))}</h3>
        <p>Every ${esc(it.name)} on this auction house${groupMore(cr) ? ` (shared with ${esc(groupOthers(cr).join(', '))})` : ''}, cheapest first. Each price is compared with the same ${it.hasVariants ? 'roll and item level' : 'item'} across EU.</p></div>
        <label class="inline-field"><span>Realm</span><select class="select" id="list-realm">${options}</select></label></div>
      ${shown.length ? `<div class="table-wrap"><table><thead><tr><th class="plain">${it.hasVariants ? 'Roll' : 'Item'}</th><th class="plain r">Price</th><th class="plain r">vs ${it.hasVariants ? 'same roll' : 'the rest of'} EU</th><th class="plain">Time left</th></tr></thead>
        <tbody>${rows}</tbody></table></div>` : '<div class="empty">No listings here match the roll you picked.</div>'}
      ${hidden ? `<div class="roll-foot"><span>${hidden} more listing${hidden === 1 ? '' : 's'} here with other rolls.</span>
        <button type="button" class="link-btn" id="list-all">Show every roll</button></div>` : ''}
    </section>`;
  }

  function render() {
    const f = {...rollFilter};
    const S = statsFor(f);
    const mine = S && myRealm && S.byCr[myRealm];
    const myRank = mine && !mine.flag ? S.sane.slice().reverse().findIndex(r => r.cr === myRealm) + 1 : null;
    const heroTip = S ? S.lo.v.tt : `${it.id}|`;
    const ilv = ilvlsOf();
    const back = document.referrer && new URL(document.referrer).origin === location.origin && new URL(document.referrer).pathname === '/ah'
      ? new URL(document.referrer).pathname + new URL(document.referrer).search : '/ah';
    const head = `
      <a class="back" href="${esc(back)}">← Back to search</a>
      <section class="hero q-${qkey(it.q)}">
        ${icon(it, 'lg', heroTip)}
        <div style="min-width:0">
          <div class="eyebrow">${esc(it.cls)} · ${esc(it.sub)}</div>
          <h2>${esc(it.name)}</h2>
          <ul class="meta">
            <li class="qtext">${QNAME[it.q] || ''}</li>
            ${it.slot ? `<li>${esc(it.slot)}</li>` : ''}
            <li>Item level ${ilv.length > 1 ? `${ilv[0]}–${ilv[ilv.length - 1]}` : (ilv[0] ?? it.ilvl)}</li>
            ${it.req ? `<li>Requires level ${it.req}</li>` : ''}
            ${it.bind ? `<li>${esc(it.bind)}</li>` : ''}
          </ul>
        </div>
        <label class="field your-realm"><span>Your realm</span>
          <select class="select" id="my-realm"><option value="">Pick your realm</option>
          ${realmList.map(r => `<option value="${r.cr}|${esc(r.name)}" ${r.cr === myRealm && r.name === myRealmName() ? 'selected' : ''}>${esc(r.name)}</option>`).join('')}</select></label>
      </section>
      ${rollsSection()}`;
    if (!S) {
      $('#item-view').innerHTML = head + `<div class="card"><div class="empty">${it.variants.length
        ? 'No listings in EU for this roll right now. <button type="button" class="link-btn" id="roll-clear2">Show every roll</button>'
        : 'Nobody in EU has this item listed right now.'}</div></div>`;
      bind(null);
      return;
    }
    const sell = S.sane.slice().reverse().slice(0, 10), buy = S.rows.slice(0, 10);
    const scaleMax = Math.max(S.hi.lo, buy[buy.length - 1].lo);
    const walls = S.rows.filter(r => r.flag === 'wall').length, highs = S.rows.filter(r => r.flag === 'high').length;
    const flagNote = S.flagged ? `Leaves out ${[walls && `${walls} price-wall listing${walls === 1 ? '' : 's'}`, highs && `${highs} far above the typical price`].filter(Boolean).join(' and ')}.` : '';
    const flip = bestFlip(f);
    const mixHint = it.hasVariants && (!f.sec || (ilv.length > 1 && f.ilvl == null))
      ? `<p class="sell-hint"><b>Selling one?</b> This list mixes ${!f.sec ? 'stat rolls' : 'item levels'}. Pick your item's ${!f.sec ? 'secondary stats' : ''}${!f.sec && ilv.length > 1 && f.ilvl == null ? ' and ' : ''}${ilv.length > 1 && f.ilvl == null ? 'item level' : ''} under Stat rolls to compare the exact same item.</p>` : '';
    $('#item-view').innerHTML = head + `
      <div class="kpis">
        <div class="kpi"><div class="eyebrow">Cheapest in EU</div><div class="val">${coins(S.lo.lo)}</div><div class="sub">${esc(groupName(S.lo.cr))}</div></div>
        <div class="kpi"><div class="eyebrow">EU median</div><div class="val">${coins(S.med)}</div><div class="sub">Middle of every realm's lowest price</div></div>
        <div class="kpi"><div class="eyebrow">Highest in EU</div><div class="val">${coins(S.hi.lo)}</div><div class="sub">${esc(groupName(S.hi.cr))}${S.flagged ? ` · ${S.flagged} outlier${S.flagged === 1 ? '' : 's'} ignored` : ''}</div></div>
        ${mine
          ? `<div class="kpi accent"><div class="eyebrow">On ${esc(groupName(myRealm))}</div><div class="val">${coins(mine.lo)}</div>
               <div class="sub">${myRank ? `#${myRank} of ${S.sane.length} for selling · ` : ''}${pct(mine.lo / S.med - 1)} vs median</div></div>`
          : `<div class="kpi ${myRealm ? 'accent' : ''}"><div class="eyebrow">Realms listing it</div><div class="val num">${S.n} <span class="faint" style="font-size:15px">of ${D.snapshot.groups}</span></div>
               <div class="sub">${myRealm ? 'Not listed on your realm: you would be the only seller' : `${S.rows.reduce((a, r) => a + r.n, 0)} listings in total`}</div></div>`}
      </div>

      ${flip && flip.s.gain > 0 ? `<div class="flip" role="note">
        <span class="with-icon">${tipIcon(it, flip.v.tt)}${it.hasVariants ? rollLabel(flip.v) : ''}</span>
        <span>Buy on <b>${esc(groupName(flip.s.lo.cr))}</b> for ${coins(flip.s.lo.lo)}</span><span class="faint" aria-hidden="true">→</span>
        <span>sell on <b>${esc(groupName(flip.s.target.cr))}</b> at ${coins(flip.s.target.lo)}</span>
        <span class="gain">≈ +${gold(flip.s.gain)}</span>
        <span class="note">${it.hasVariants ? 'Same item, same stat roll and item level on both sides. ' : ''}After the 5% auction cut. The sell side is a typical realm's price (the median), not the priciest ask, which often never sells. These are asking prices, not sales.</span>
      </div>` : ''}

      ${listingsCard(f, S)}

      <div class="two">
        <section class="card"><div class="card-head"><div><h3>Best realms to sell</h3><p>Highest lowest-listing right now. Undercut it and you're the cheapest there. ${flagNote}</p>${mixHint}</div></div>
          ${rankList(sell, 'var(--gold-mark)', scaleMax)}</section>
        <section class="card"><div class="card-head"><div><h3>Cheapest realms to buy</h3><p>Lowest listings in EU, on the same scale as the list beside it.</p></div></div>
          ${rankList(buy, 'var(--arcane-mark)', scaleMax)}</section>
      </div>

      <div class="stack">
        <section class="card"><div class="card-head"><div><h3>Every realm's lowest price</h3>
          <p>One dot per realm group. The axis is logarithmic, because prices for one item can differ more than tenfold between realms.</p></div></div>
          <div class="legend"><span><i class="dot" style="--c:var(--arcane-mark)"></i>Realm group</span>
            ${myRealm ? '<span><i class="dot" style="--c:var(--gold-mark)"></i>Your realm</span>' : ''}
            ${S.flagged ? '<span><i class="ring"></i>Price wall or far above typical</span>' : ''}
            <span><i style="--c:var(--muted)"></i>EU median</span></div>
          <div class="chart-box" id="strip"></div></section>

        <section class="card"><div class="card-head"><div><h3>Price history</h3>
          <p>The EU median of every realm's cheapest listing, with the middle half of realms shaded${myRealm ? ', and your realm' : ''}${it.hasVariants ? '. Covers every roll of this item' : ''}.</p></div></div>
          <div class="legend"><span><i style="--c:var(--arcane-mark)"></i>EU median</span><span><i class="band" style="--c:var(--arcane-mark)"></i>Middle 50% of realms</span>
            ${myRealm ? '<span><i style="--c:var(--gold-mark)"></i>Your realm</span>' : ''}</div>
          <div class="chart-box" id="history"></div></section>

        <section class="card"><div class="card-head"><div><h3>All ${S.n} realm groups</h3><p>Connected realms share one auction house, so they share a row.${it.hasVariants ? " Hover a roll's icon for its tooltip." : ''}</p></div></div>
          <div class="table-tools"><input class="input" id="realm-filter" type="search" placeholder="Filter realms" aria-label="Filter realms">
            <span class="small faint" id="realm-count"></span></div>
          <div class="table-wrap"><table id="realm-table"><thead></thead><tbody></tbody></table></div></section>
      </div>`;
    bind(S);
    renderRealmTable(S);
    drawStrip(S); drawHistory();
  }

  // re-render in place; a keyboard user keeps focus on the control they used
  function rerender(focusSel) {
    hideItemTip();
    const y = window.scrollY;
    render();
    window.scrollTo(0, y);
    if (focusSel) { const el = $(focusSel); if (el) el.focus({preventScroll: true}); }
    const p = new URLSearchParams(rollQuery({sec: rollFilter.sec, ter: rollFilter.ter, sock: rollFilter.sock === 'yes', ilvl: rollFilter.ilvl}));
    if (rollFilter.sock === 'no') p.set('sock', 'no');
    history.replaceState(null, '', location.pathname + (p.toString() ? '?' + p : ''));
  }
  function bind(S) {
    $('#my-realm').onchange = e => {
      const [cr, name] = e.target.value.split('|');
      myRealm = cr ? +cr : null;
      store.set('ah-my-realm', cr || ''); store.set('ah-my-realm-name', name || '');
      rerender('#my-realm');
    };
    const rolls = $('#item-view .rolls');
    if (rolls) {
      rolls.onclick = e => {
        const row = e.target.closest('.roll-row[role="radio"]'), lvl = e.target.closest('.seg button');
        if (row) rollFilter.sec = row.dataset.sec;
        else if (lvl) rollFilter.ilvl = lvl.dataset.ilvl === '' ? null : +lvl.dataset.ilvl;
        else if (e.target.closest('#roll-clear')) rollFilter = {sec: '', ter: '', sock: '', ilvl: null};
        else return;
        const keyboard = e.detail === 0;
        rerender(!keyboard ? null : row ? `.roll-row[data-sec="${CSS.escape(row.dataset.sec)}"]`
          : lvl ? `.seg button[data-ilvl="${lvl.dataset.ilvl}"]` : '#my-realm');
      };
      rolls.onchange = e => {
        const id = e.target.id;
        if (id === 'roll-ilvl') rollFilter.ilvl = e.target.value === '' ? null : +e.target.value;
        else if (id === 'roll-ter') rollFilter.ter = e.target.value;
        else if (id === 'roll-sock') rollFilter.sock = e.target.value;
        else return;
        rerender('#' + id);
      };
    }
    const lr = $('#list-realm');
    if (lr) lr.onchange = () => { listRealm = +lr.value; rerender('#list-realm'); };
    const la = $('#list-all');
    if (la) la.onclick = e => { rollFilter = {sec: '', ter: '', sock: '', ilvl: null}; rerender(e.detail === 0 ? '#list-realm' : null); };
    const clear2 = $('#roll-clear2');
    if (clear2) clear2.onclick = () => { rollFilter = {sec: '', ter: '', sock: '', ilvl: null}; rerender(); };
    if (!S) return;
    $('#realm-filter').oninput = () => renderRealmTable(S);
    $('#realm-table thead').onclick = e => {
      const b = e.target.closest('[data-sort]'); if (!b) return;
      const k = b.dataset.sort;
      tableSort = tableSort.key === k ? {key: k, dir: -tableSort.dir} : {key: k, dir: k === 'name' ? 1 : -1};
      renderRealmTable(S);
    };
  }

  function renderRealmTable(S) {
    const f = ($('#realm-filter').value || '').trim().toLowerCase();
    const cols = [['name', 'Realm group'], ['lang', 'Language'], ['pop', 'Population'], ...(it.hasVariants ? [['roll', 'Cheapest roll']] : []),
                  ['lo', 'Lowest', 'r'], ['n', 'Listings', 'r'], ['vs', 'vs EU median', 'r']];
    const v = (r, k) => ({name: groupName(r.cr), lang: (realmGroups[r.cr] || {}).locale || '', pop: (realmGroups[r.cr] || {}).pop || '',
                          roll: (r.v.sec || '') + r.v.ilvl, lo: r.lo, n: r.n, vs: r.lo / S.med}[k]);
    const rows = S.rows.filter(r => !f || ((realmGroups[r.cr] || {}).names || []).some(n => n.toLowerCase().includes(f)))
      .sort((a, b) => { const x = v(a, tableSort.key), y = v(b, tableSort.key); return (typeof x === 'string' ? x.localeCompare(y) : x - y) * tableSort.dir; });
    $('#realm-table thead').innerHTML = '<tr>' + cols.map(([k, l, c]) => `<th class="${c || ''}" ${k === tableSort.key ? `aria-sort="${tableSort.dir > 0 ? 'ascending' : 'descending'}"` : ''}>
      <button type="button" class="sort" data-sort="${k}">${l}</button></th>`).join('') + '</tr>';
    $('#realm-table tbody').innerHTML = rows.map(r => {
      const g = realmGroups[r.cr] || {names: [], locale: '', pop: ''}, d = r.lo / S.med - 1;
      return `<tr class="${r.cr === myRealm ? 'you' : ''} ${r.flag ? 'flagged' : ''}"><td><b style="font-weight:600">${esc(groupName(r.cr))}</b>${r.cr === myRealm ? '<span class="you-tag">YOU</span>' : ''}
        ${r.flag ? `<span class="flag-tag" title="${esc(flagText(r))}">${r.flag === 'wall' ? 'Price wall' : 'Far above'}</span>` : ''}
        ${g.names.length > 1 ? `<span class="realm-tag">${esc(groupOthers(r.cr).join(', '))}</span>` : ''}</td>
        <td><span class="lang" title="${esc(LANG[g.locale] || g.locale)}">${esc((g.locale || '').toUpperCase())}</span></td>
        <td class="muted">${esc(POP[g.pop] || g.pop || '–')}</td>
        ${it.hasVariants ? `<td><span class="with-icon">${tipIcon(it, r.v.tt, `<b>${esc(groupName(r.cr))}</b> · ${gold(r.lo)}`)}${rollLabel(r.v)}</span></td>` : ''}
        <td class="r">${coins(r.lo)}</td><td class="r num">${r.n}</td>
        <td class="r num ${d < -0.05 ? 'delta-down' : d > 0.05 ? 'delta-up' : 'muted'}">${pct(d)}</td></tr>`;
    }).join('') || `<tr><td colspan="${cols.length}"><div class="empty">No realm group matches “${esc(f)}”.</div></td></tr>`;
    $('#realm-count').textContent = `${rows.length} of ${S.n} shown`;
  }

  function logTicks(lo, hi) {
    const out = [];
    for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++)
      for (const m of [1, 2, 5]) { const v = m * 10 ** e; if (v >= lo && v <= hi) out.push(v); }
    if (out.length > 7) return out.filter(v => /^1/.test(String(v)));
    if (out.length >= 3) return out;
    const fine = [];
    for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++)
      for (let m = 1; m <= 9; m++) { const v = m * 10 ** e; if (v >= lo && v <= hi) fine.push(v); }
    return fine;
  }

  function drawStrip(S) {
    const box = $('#strip');
    const W = Math.max(320, box.clientWidth), padL = 16, padR = 16, top = 26, r = 5.5;
    const lows = S.rows.map(x => x.lo);
    const lo = Math.min(...lows) / 1.25, hi = Math.max(...lows) * 1.25;
    const x = v => padL + (Math.log(v) - Math.log(lo)) / (Math.log(hi) - Math.log(lo)) * (W - padL - padR);
    const placed = [];
    const pts = S.rows.map(row => ({row, x: x(row.lo)})).sort((a, b) => a.x - b.x);
    let maxOff = 0;
    for (const p of pts) {
      for (let k = 0; ; k++) {
        const off = (k % 2 ? 1 : -1) * Math.ceil(k / 2) * (r * 2 + 1.5);
        if (!placed.some(q => Math.abs(q.x - p.x) < r * 2 + 1.5 && Math.abs(q.off - off) < r * 2 + 1.5)) { p.off = off; break; }
      }
      placed.push(p); maxOff = Math.max(maxOff, Math.abs(p.off));
    }
    const mid = top + maxOff + r + 4, H = mid + maxOff + r + 34;
    let s = logTicks(lo, hi).map(t => `<line class="grid" x1="${x(t)}" x2="${x(t)}" y1="${top - 8}" y2="${H - 24}"/>
      <text x="${x(t)}" y="${H - 8}" text-anchor="middle">${gold(t)}</text>`).join('');
    const mx = x(S.med);
    const anchor = mx < 90 ? 'start' : mx > W - 90 ? 'end' : 'middle';
    s += `<line x1="${mx}" x2="${mx}" y1="${top - 14}" y2="${H - 24}" stroke="var(--muted)" stroke-width="1.5" stroke-dasharray="4 4"/>
      <text x="${mx}" y="${top - 16}" text-anchor="${anchor}" class="lbl-strong">EU median ${gold(S.med)}</text>`;
    const mine = pts.find(p => p.row.cr === myRealm);
    for (const p of pts) if (p !== mine)
      s += `<g data-cr="${p.row.cr}"><circle cx="${p.x}" cy="${mid + p.off}" r="${r + 5}" fill="transparent"/>
        ${p.row.flag
          ? `<circle cx="${p.x}" cy="${mid + p.off}" r="${r - 0.75}" fill="var(--surface)" stroke="var(--faint)" stroke-width="1.5"/>`
          : `<circle cx="${p.x}" cy="${mid + p.off}" r="${r}" fill="var(--arcane-mark)" stroke="var(--surface)" stroke-width="1.5"/>`}</g>`;
    if (mine) s += `<g data-cr="${mine.row.cr}"><circle cx="${mine.x}" cy="${mid + mine.off}" r="${r + 7}" fill="transparent"/>
        <circle cx="${mine.x}" cy="${mid + mine.off}" r="${r + 2}" fill="var(--gold-mark)" stroke="var(--surface)" stroke-width="2"/></g>`;
    box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Lowest price on each of ${S.n} realm groups">${s}</svg>`;
    const svg = box.querySelector('svg');
    svg.addEventListener('pointermove', e => {
      const g = e.target.closest('[data-cr]');
      if (!g) return hideTip();
      const row = S.byCr[g.dataset.cr];
      const roll = it.hasVariants ? `<br>${esc(rollText(row.v)) || 'No extra stats'} · ilvl ${row.v.ilvl}` : '';
      showTip(`<b>${esc(((realmGroups[row.cr] || {}).names || []).join(', '))}</b>${coins(row.lo)} lowest · ${row.n} listing${row.n === 1 ? '' : 's'}${roll}<br>
        <span class="muted">${pct(row.lo / S.med - 1)} vs EU median</span>${flagText(row) ? `<br><span class="muted">${flagText(row)}</span>` : ''}`, e.clientX, e.clientY);
    });
    svg.addEventListener('pointerleave', hideTip);
  }

  // Real history: the item's hourly EU numbers (one a day after two weeks), and your realm's cheapest price per day
  function drawHistory() {
    const box = $('#history');
    const pts = (D.history || []).map(([t, lo, p25, med, p75]) => ({t: Date.parse(t), lo, p25, med, p75})).filter(p => p.med > 0);
    if (pts.length < 2) {
      box.innerHTML = `<div class="empty">The history starts with the first collection${D.snapshot.history_since ? ` (${new Date(D.snapshot.history_since).toLocaleDateString('en-GB', {day: 'numeric', month: 'short'})})` : ''}. Check back in a few hours.</div>`;
      return;
    }
    const mineRaw = myRealm ? ((D.realm_history || {})[myRealm] || []) : [];
    const mine = mineRaw.map(([day, lo]) => ({t: Date.parse(day + 'T12:00:00Z'), v: lo}));
    const W = Math.max(320, box.clientWidth), H = 240, padL = 64, padR = 16, top = 14, bot = 30;
    const t0 = Math.min(pts[0].t, ...mine.map(m => m.t)), t1 = Math.max(pts[pts.length - 1].t, ...mine.map(m => m.t));
    const values = [...pts.flatMap(p => [p.p25, p.p75, p.med]), ...mine.map(m => m.v)];
    const yMin = Math.min(...values) * 0.92, yMax = Math.max(...values) * 1.06;
    const x = t => padL + (t1 > t0 ? (t - t0) / (t1 - t0) : 0.5) * (W - padL - padR);
    const y = v => top + (1 - (v - yMin) / (yMax - yMin || 1)) * (H - top - bot);
    const step = (() => { const raw = (yMax - yMin) / 4 || 1, p = 10 ** Math.floor(Math.log10(raw)); return [1, 2, 2.5, 5, 10].map(m => m * p).find(m => m >= raw); })();
    let s = '';
    for (let v = Math.ceil(yMin / step) * step; v <= yMax; v += step)
      s += `<line class="grid" x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}"/><text x="${padL - 8}" y="${y(v) + 4}" text-anchor="end">${gold(v)}</text>`;
    const days = (t1 - t0) / 864e5;
    const tickEvery = days > 60 ? 14 : days > 20 ? 7 : days > 6 ? 2 : days > 1.5 ? 1 : 0.25;
    const first = Math.ceil(t0 / (tickEvery * 864e5)) * tickEvery * 864e5;
    for (let t = first; t <= t1; t += tickEvery * 864e5) {
      const d = new Date(t);
      const label = tickEvery < 1 ? d.toLocaleTimeString('en-GB', {hour: '2-digit', minute: '2-digit'}) : d.toLocaleDateString('en-GB', {day: 'numeric', month: 'short'});
      s += `<text x="${x(t)}" y="${H - 8}" text-anchor="middle">${label}</text>`;
    }
    const path = arr => arr.map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join('');
    s += `<path d="${path(pts.map(p => [p.t, p.p75]))}L${pts.slice().reverse().map(p => `${x(p.t).toFixed(1)},${y(p.p25).toFixed(1)}`).join('L')}Z" fill="var(--arcane-mark)" opacity="0.18"/>`;
    s += `<path d="${path(pts.map(p => [p.t, p.med]))}" fill="none" stroke="var(--arcane-mark)" stroke-width="2" stroke-linejoin="round"/>`;
    if (mine.length > 1) s += `<path d="${path(mine.map(m => [m.t, m.v]))}" fill="none" stroke="var(--gold-mark)" stroke-width="2" stroke-linejoin="round"/>`;
    const last = pts[pts.length - 1];
    s += `<circle cx="${x(last.t)}" cy="${y(last.med)}" r="4.5" fill="var(--arcane-mark)" stroke="var(--surface)" stroke-width="2"/>`;
    if (mine.length) { const m = mine[mine.length - 1]; s += `<circle cx="${x(m.t)}" cy="${y(m.v)}" r="4.5" fill="var(--gold-mark)" stroke="var(--surface)" stroke-width="2"/>`; }
    s += `<line id="hx" y1="${top}" y2="${H - bot}" stroke="var(--line-strong)" visibility="hidden"/>
          <rect x="${padL}" y="${top}" width="${W - padL - padR}" height="${H - top - bot}" fill="transparent" id="hhit"/>`;
    box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="EU price history">${s}</svg>`;
    const svg = box.querySelector('svg'), hx = svg.querySelector('#hx');
    svg.querySelector('#hhit').addEventListener('pointermove', e => {
      const rect = svg.getBoundingClientRect(), sx = (e.clientX - rect.left) * W / rect.width;
      const t = t0 + (sx - padL) / (W - padL - padR) * (t1 - t0);
      const p = pts.reduce((best, q) => Math.abs(q.t - t) < Math.abs(best.t - t) ? q : best, pts[0]);
      const m = mine.length ? mine.reduce((best, q) => Math.abs(q.t - t) < Math.abs(best.t - t) ? q : best, mine[0]) : null;
      hx.setAttribute('x1', x(p.t)); hx.setAttribute('x2', x(p.t)); hx.setAttribute('visibility', 'visible');
      const when = new Date(p.t).toLocaleString('en-GB', {weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
      showTip(`<b>${when}</b>EU median ${coins(p.med)}<br><span class="muted">Middle 50%: ${gold(p.p25)} – ${gold(p.p75)} · cheapest ${gold(p.lo)}</span>
        ${m && Math.abs(m.t - p.t) < 864e5 ? `<br>Your realm that day ${coins(m.v)}` : ''}`, e.clientX, e.clientY);
    });
    svg.querySelector('#hhit').addEventListener('pointerleave', () => { hx.setAttribute('visibility', 'hidden'); hideTip(); });
  }

  let rz;
  window.addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(render, 150); });
  render();
}
})();
