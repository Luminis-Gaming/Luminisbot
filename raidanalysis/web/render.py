"""HTML building blocks for the raid analysis pages (charts, tables, formatting)."""
import html

DIFFICULTY_NAMES = {1: 'LFR', 3: 'Normal', 4: 'Heroic', 5: 'Mythic'}

CLASS_COLORS = {
    'DeathKnight': '#C41E3A', 'DemonHunter': '#A330C9', 'Druid': '#FF7C0A', 'Evoker': '#33937F',
    'Hunter': '#AAD372', 'Mage': '#3FC7EB', 'Monk': '#00FF98', 'Paladin': '#F48CBA',
    'Priest': '#FFFFFF', 'Rogue': '#FFF468', 'Shaman': '#0070DD', 'Warlock': '#8788EE',
    'Warrior': '#C69B6D',
}
ROLE_ICONS = {'tank': '🛡️', 'healer': '💚', 'dps': '⚔️'}

# Chart series colors - validated (dataviz validate_palette.js, dark mode) on the card surface (#161a2c).
SERIES_PULL = '#7484ec'
SERIES_BEST = '#cc7f3c'
STATUS_GOOD = '#51cf66'

ICON_BASE = 'https://assets.rpglogs.com/img/warcraft/abilities/'

PAGE_CSS = """
/* Raid analysis theme - layered over the shared ADMIN_CSS, raid pages only. */
:root {
    --bg: #0d1020; --surface: #161a2c; --surface-2: #1d2238; --surface-3: #252b45;
    --border: rgba(255,255,255,0.07); --border-strong: rgba(255,255,255,0.14);
    --text: #e7e9f3; --muted: #9aa1b9; --faint: #6b7290;
    --accent: #6d7cff; --accent-soft: rgba(109,124,255,0.16);
    --good: #51cf66; --good-soft: rgba(81,207,102,0.14);
    --warn: #fcc419; --warn-soft: rgba(252,196,25,0.14);
    --bad: #ff6b6b; --bad-soft: rgba(255,107,107,0.14);
    --radius: 14px;
}
body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: radial-gradient(1200px 600px at 10% -10%, rgba(109,124,255,0.10), transparent 60%), var(--bg);
    color: var(--text); font-size: 15px; line-height: 1.5; -webkit-font-smoothing: antialiased; }
.container { max-width: 1280px; }
h1 { font-size: 26px; font-weight: 700; letter-spacing: -0.02em; margin-bottom: 8px; }
h2 { font-size: 18px; font-weight: 650; letter-spacing: -0.01em; margin-bottom: 14px; }
h3 { font-size: 15px; font-weight: 600; margin: 0; }
h4 { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; color: var(--muted);
    margin: 18px 0 8px; }
a { color: #9aa6ff; text-decoration: none; }
a:hover { text-decoration: underline; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
    box-shadow: 0 1px 0 rgba(255,255,255,0.03) inset, 0 10px 30px rgba(0,0,0,0.25);
    backdrop-filter: none; padding: 24px; margin-bottom: 16px; }
.nav { gap: 8px; margin-bottom: 20px; }
.nav a { background: transparent; border: 1px solid var(--border); padding: 8px 14px; font-size: 14px; color: var(--muted); }
.nav a:hover { background: var(--surface-2); color: var(--text); text-decoration: none; }
.nav a.active { background: var(--accent-soft); border-color: var(--accent); color: var(--text); }
.btn { border-radius: 10px; font-weight: 600; }
.btn-primary { background: var(--accent); }
.btn-secondary { background: var(--surface-3); border: 1px solid var(--border); }
.btn-sm { padding: 7px 14px; font-size: 13px; }
input[type="text"], input[type="number"], select { background: var(--surface-2); border: 1px solid var(--border-strong);
    border-radius: 10px; color: var(--text); }
.stat { background: var(--surface-2); border: 1px solid var(--border); }
.stat-value { color: var(--text); }
.success { color: var(--good); }
.error { color: var(--bad); }
.warning-box { background: var(--warn-soft); border: 1px solid rgba(252,196,25,0.35); color: var(--text); }
code { background: var(--surface-3); }

.muted { color: var(--muted); }
.small { font-size: 13px; }
.good-text { color: var(--good); }
.bad-text { color: var(--bad); }
.ability-cell { white-space: nowrap; }
.ability-icon { width: 20px; height: 20px; border-radius: 5px; vertical-align: middle; margin-right: 7px;
    box-shadow: 0 0 0 1px rgba(0,0,0,0.4); }

.pill { padding: 2px 9px; border-radius: 999px; font-size: 12px; font-weight: 600; white-space: nowrap;
    border: 1px solid transparent; }
.pill-kill { background: var(--good-soft); color: var(--good); }
.pill-wipe { background: var(--surface-3); color: var(--text); }
.pill-diff { background: var(--accent-soft); color: #c3c9ff; }
.pill-avoidable { background: var(--bad-soft); color: #ff9b9b; }
.pill-ignore { background: var(--surface-3); color: var(--muted); }
.pill-suggest { background: var(--warn-soft); color: var(--warn); }

/* Tables */
table { border-collapse: separate; border-spacing: 0; }
th { background: transparent; color: var(--muted); font-size: 11px; font-weight: 600; letter-spacing: .06em;
    border-bottom: 1px solid var(--border-strong); }
td { border-bottom: 1px solid var(--border); }
tr:hover td { background: rgba(255,255,255,0.025); }
table.compact th, table.compact td { padding: 9px 10px; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
td.bad { color: var(--bad); font-weight: 600; }
td.good { color: var(--good); }
th[data-sort] { cursor: pointer; user-select: none; }
th[data-sort]:hover { color: var(--text); }
.table-wrapper { overflow-x: auto; }

/* Charts */
.chart { width: 100%; height: auto; display: block; margin: 10px 0 18px; }
.chart text { fill: var(--muted); font-size: 11px; font-family: inherit; }
.chart .grid { stroke: rgba(255,255,255,0.06); }
.chart .axis-label { fill: var(--faint); }
.chart a:hover circle.mark { stroke: #fff; stroke-width: 2; }
.legend { display: flex; gap: 18px; font-size: 13px; color: var(--muted); flex-wrap: wrap; }
.legend span::before { content: ''; display: inline-block; width: 14px; height: 3px; border-radius: 2px;
    background: var(--c); vertical-align: middle; margin-right: 6px; }
table.bars td.bar-cell { width: 55%; }
.bar { height: 8px; border-radius: 0 4px 4px 0; background: #7484ec; }

.grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(420px, 100%), 1fr)); gap: 16px; }
.grid-2 > * { min-width: 0; }
.grid-2 > .card { margin-bottom: 0; }

/* Tagging */
.tag-form { display: inline-flex; gap: 4px; }
.tag-form button { padding: 4px 10px; font-size: 12px; border-radius: 7px; border: 1px solid var(--border);
    cursor: pointer; background: var(--surface-2); color: var(--muted); white-space: nowrap; }
.tag-form button:hover { color: var(--text); border-color: var(--border-strong); }
.tag-form button.on-avoidable, .tag-form button.on-avoidable_nontank { background: #c92a2a; color: #fff; border-color: #c92a2a; }
.tag-form button.on-ignore { background: var(--surface-3); color: var(--text); }
.inline-form { display: inline-flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.inline-form input[type=text], .inline-form input[type=number] { width: auto; margin: 0; padding: 8px 12px; font-size: 14px; }

/* Night header: boss tabs, pull chips, view switch */
.sync-banner { padding: 14px 20px; border-color: rgba(109,124,255,0.5); background: var(--accent-soft); }
.sync-banner[hidden] { display: none; }
.boss-tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 18px; }
.boss-tab { padding: 10px 14px; border-radius: 12px; background: var(--surface-2); color: var(--text);
    border: 1px solid var(--border); transition: border-color .15s, background .15s; }
.boss-tab:hover { border-color: var(--border-strong); text-decoration: none; }
.boss-tab.active { border-color: var(--accent); background: var(--accent-soft); }
.boss-tab small { display: block; color: var(--muted); margin-top: 2px; }
.pull-chips { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 12px; align-items: center; }
.pull-chip { padding: 4px 10px; border-radius: 8px; background: var(--surface-2); color: var(--text);
    font-size: 13px; font-variant-numeric: tabular-nums; border: 1px solid var(--border); cursor: pointer;
    font-family: inherit; }
.pull-chip:hover { border-color: var(--border-strong); text-decoration: none; }
.pull-chip.kill { color: var(--good); }
.pull-chip.overall { font-weight: 600; }
.pull-chip.active { border-color: var(--accent); background: var(--accent-soft); }
.view-tabs { display: flex; gap: 4px; margin: 18px -24px -24px; padding: 0 20px; border-top: 1px solid var(--border); }
.view-tab { padding: 12px 14px; color: var(--muted); font-weight: 600; font-size: 14px;
    border-bottom: 2px solid transparent; }
.view-tab:hover { color: var(--text); text-decoration: none; }
.view-tab.active { color: var(--text); border-bottom-color: var(--accent); }

/* Mechanics list */
.insight { border: 1px solid var(--border); border-left: 3px solid var(--border-strong); background: var(--surface-2);
    border-radius: 10px; margin-bottom: 6px; }
.insight.bad { border-left-color: var(--bad); }
.insight.good { border-left-color: var(--good); }
.insight > summary { padding: 11px 14px; cursor: pointer; list-style: none; display: flex; gap: 10px;
    align-items: center; }
.insight > summary:hover { background: rgba(255,255,255,0.02); }
.insight > summary::-webkit-details-marker { display: none; }
.insight > summary::after { content: '▸'; margin-left: auto; color: var(--faint); }
.insight[open] > summary::after { content: '▾'; }
.insight .insight-body { padding: 2px 14px 14px; }
.insight-group { margin: 18px 0 8px; font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: .08em; color: var(--faint); }

/* Players */
.player-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(340px, 100%), 1fr)); gap: 14px;
    margin-bottom: 16px; }
.player-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 18px; display: flex; flex-direction: column; gap: 12px; }
.player-card[hidden] { display: none; }
.player-card header { display: flex; gap: 14px; align-items: center; }
.player-card .card-link { margin-top: auto; font-size: 13px; }
.player-hero { display: flex; gap: 24px; align-items: center; flex-wrap: wrap; }
.player-hero h2 { margin: 0 0 4px; font-size: 22px; }
.score-ring { --p: 0; --c: var(--accent); width: 64px; height: 64px; border-radius: 50%; flex: none;
    display: grid; place-items: center; align-content: center; position: relative;
    background: conic-gradient(var(--c) calc(var(--p) * 1%), var(--surface-3) 0); }
.score-ring::before { content: ''; position: absolute; inset: 6px; border-radius: 50%; background: var(--surface); }
.score-ring > * { position: relative; line-height: 1.05; text-align: center; }
.score-ring span { font-size: 19px; font-weight: 700; }
.score-ring small { font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
.score-ring.lg { width: 104px; height: 104px; }
.score-ring.lg::before { inset: 9px; }
.score-ring.lg span { font-size: 32px; }
.score-ring.lg small { font-size: 11px; }
.score-ring.good { --c: var(--good); } .score-ring.ok { --c: var(--warn); } .score-ring.bad { --c: var(--bad); }
.subscores { display: grid; gap: 6px; }
.subscores.wide { max-width: 460px; margin-top: 10px; }
.subscore { display: grid; grid-template-columns: 78px 1fr 30px; gap: 10px; align-items: center; font-size: 12px;
    color: var(--muted); }
.subscore b { color: var(--text); text-align: right; font-variant-numeric: tabular-nums; }
.subscore-track { height: 6px; border-radius: 3px; background: var(--surface-3); overflow: hidden; }
.subscore-fill { height: 100%; border-radius: 3px; }
.subscore-fill.good { background: var(--good); } .subscore-fill.ok { background: var(--warn); }
.subscore-fill.bad { background: var(--bad); }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chips:empty { display: none; }
.chip { font-size: 12px; padding: 3px 9px; border-radius: 999px; background: var(--surface-2);
    border: 1px solid var(--border); color: var(--muted); }
.notes { list-style: none; padding: 0; margin: 0; display: grid; gap: 6px; }
.note { display: flex; gap: 8px; font-size: 13.5px; padding: 8px 10px; border-radius: 9px; background: var(--surface-2); }
.note.bad { background: var(--bad-soft); }
.note.good { background: var(--good-soft); }

/* Phase heatmap + wipe reasons + trends */
table.heatmap td.heat { background: rgba(116,132,236,var(--a)); color: var(--text); font-weight: 600; }
table.heatmap td.heat small { color: var(--muted); font-weight: 400; }
.reason { font-weight: 600; }
.reason-detail { display: block; font-size: 12px; color: var(--muted); }
.trend-up { color: var(--good); font-weight: 600; }
.trend-down { color: var(--bad); font-weight: 600; }
.spark { width: 120px; height: 28px; vertical-align: middle; }

/* Clips */
.clip-btn { margin-left: 6px; padding: 1px 8px; font-size: 11px; border: none; border-radius: 10px;
    background: #c92a2a; color: #fff; cursor: pointer; vertical-align: middle; }
.clip-btn:hover { background: #e03131; }
.guide-info { margin-left: 4px; cursor: help; font-size: 13px; }
.clip-modal { position: fixed; inset: 0; background: rgba(5,7,15,0.75); display: flex; align-items: center;
    justify-content: center; z-index: 100; padding: 16px; backdrop-filter: blur(4px); }
.clip-modal[hidden] { display: none; }
.clip-box { background: var(--surface); border: 1px solid var(--border-strong); border-radius: 16px; padding: 18px;
    width: min(680px, 100%); max-height: 100%; overflow: auto; box-shadow: 0 20px 60px rgba(0,0,0,0.6); }
.clip-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.clip-head h3 { margin: 0; font-size: 17px; }
.clip-close { background: var(--surface-3); border: none; color: var(--text); border-radius: 8px;
    padding: 6px 10px; cursor: pointer; }
.clip-box iframe { width: 100%; height: 620px; max-height: 70vh; border: 0; border-radius: 10px; background: #000; }

@media (max-width: 600px) {
    body { padding: 10px; } .card { padding: 16px; }
    .view-tabs { margin: 14px -16px -16px; padding: 0 8px; }
    .grid-2 { grid-template-columns: 1fr; }
}
"""

# Sortable tables + local timestamps. Kept dependency-free.
PAGE_JS = """
document.querySelectorAll('[data-ts]').forEach(el => {
  const d = new Date(+el.dataset.ts);
  el.textContent = el.dataset.fmt === 'time'
    ? d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})
    : d.toLocaleDateString([], {weekday: 'short', year: 'numeric', month: 'short', day: 'numeric'})
      + (el.dataset.fmt === 'date' ? '' : ' ' + d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}));
});
document.querySelectorAll('th[data-sort]').forEach(th => th.addEventListener('click', () => {
  const table = th.closest('table'), idx = [...th.parentNode.children].indexOf(th);
  const rows = [...table.querySelectorAll('tr')].filter(r => r.querySelector('td'));
  const asc = th.dataset.dir !== 'asc'; th.dataset.dir = asc ? 'asc' : 'desc';
  const val = r => { const c = r.children[idx]; const v = c.dataset.v ?? c.textContent.trim();
                     return isNaN(+v) || v === '' ? v.toLowerCase() : +v; };
  rows.sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * (asc ? 1 : -1));
  rows.forEach(r => r.parentNode.appendChild(r));
}));
// Sync progress: poll while a sync runs, refresh once it brought in something new
// (or this page is waiting for a report that's being imported).
const syncBanner = document.getElementById('sync-banner');
if (syncBanner && syncBanner.dataset.running === '1') {
  const poll = async () => {
    try {
      const s = await (await fetch('/admin/raids/sync/status', {credentials: 'same-origin'})).json();
      if (!s.running) {
        if (s.last_new > 0 || syncBanner.dataset.waiting === '1') {
          const url = new URL(location.href); url.searchParams.delete('msg'); location.replace(url);
        } else {
          syncBanner.hidden = true;
        }
        return;
      }
      syncBanner.querySelector('span').textContent = s.current || 'Working…';
    } catch (e) { /* transient - keep polling */ }
    setTimeout(poll, 2500);
  };
  setTimeout(poll, 2500);
}
// Players view: filter cards by role.
document.querySelectorAll('.role-filter').forEach(btn => btn.addEventListener('click', () => {
  document.querySelectorAll('.role-filter').forEach(b => b.classList.toggle('active', b === btn));
  document.querySelectorAll('.player-card').forEach(card => {
    card.hidden = btn.dataset.role !== 'all' && card.dataset.role !== btn.dataset.role;
  });
}));
document.querySelectorAll('.expand-all').forEach(btn => btn.addEventListener('click', () => {
  const items = btn.closest('.card').querySelectorAll('details.insight');
  const open = [...items].some(d => !d.open);
  items.forEach(d => { d.open = open; });
  btn.textContent = open ? 'Collapse all' : 'Expand all';
}));
// Mechanic clip pop-up: the Mythic Trap iframe only loads when someone opens it.
document.addEventListener('click', e => {
  const btn = e.target.closest('.clip-btn');
  const modal = document.getElementById('clip-modal');
  if (btn) {
    e.preventDefault(); e.stopPropagation();
    modal.querySelector('h3').textContent = btn.dataset.title;
    modal.querySelector('.clip-tip').textContent = btn.dataset.tip || '';
    modal.querySelector('iframe').src = btn.dataset.embed;
    modal.querySelector('.clip-link').href = btn.dataset.embed.replace('/embed-ability/', '/').replace(/\\/[^/]+$/, '');
    modal.hidden = false;
  } else if (modal && !modal.hidden && (e.target === modal || e.target.closest('.clip-close'))) {
    modal.hidden = true; modal.querySelector('iframe').src = 'about:blank';
  }
});
document.addEventListener('keydown', e => {
  const modal = document.getElementById('clip-modal');
  if (e.key === 'Escape' && modal && !modal.hidden) { modal.hidden = true; modal.querySelector('iframe').src = 'about:blank'; }
});
"""

CLIP_MODAL = """
<div id="clip-modal" class="clip-modal" hidden>
  <div class="clip-box" role="dialog" aria-modal="true">
    <div class="clip-head"><h3></h3><button class="clip-close" aria-label="Close">✕</button></div>
    <p class="clip-tip muted small"></p>
    <iframe title="Mechanic clip" loading="lazy" allow="autoplay; fullscreen"></iframe>
    <p class="muted small">Clip by <a class="clip-link" target="_blank" rel="noopener">Mythic Trap ↗</a></p>
  </div>
</div>
"""


def sync_banner(status, waiting=False):
    """Live progress line while a WCL sync runs (see the polling in PAGE_JS)."""
    running = status.get('running')
    return (f'<div id="sync-banner" class="card sync-banner" data-running="{1 if running else 0}" '
            f'data-waiting="{1 if waiting else 0}"{"" if running else " hidden"}>⏳ '
            f'<span>{esc(status.get("current") or "Starting sync…")}</span> '
            f'<small class="muted">— the page updates itself when it’s done.</small></div>')


def esc(value):
    return html.escape(str(value if value is not None else ''))


def fmt_duration(ms):
    seconds = int((ms or 0) / 1000)
    if seconds >= 3600:
        return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"
    return f"{seconds // 60}:{seconds % 60:02d}"


def fmt_amount(n):
    n = n or 0
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(int(n))


def ts(epoch_ms, fmt='datetime'):
    """Rendered client-side in the viewer's timezone (see PAGE_JS)."""
    return f'<span data-ts="{int(epoch_ms)}" data-fmt="{fmt}"></span>'


def difficulty_pill(difficulty):
    return f'<span class="pill pill-diff">{esc(DIFFICULTY_NAMES.get(difficulty, difficulty))}</span>'


def player_name(name, cls='', role=None):
    color = CLASS_COLORS.get(cls, '#ddd')
    icon = f'{ROLE_ICONS.get(role, "")} ' if role else ''
    return f'{icon}<span style="color:{color};font-weight:600">{esc(name)}</span>'


def ability(name, icon=None, ability_id=None, guide=None):
    img = f'<img class="ability-icon" src="{ICON_BASE}{esc(icon)}" alt="" loading="lazy">' if icon else ''
    label = esc(name)
    if ability_id and ability_id > 1:
        label = (f'<a href="https://www.wowhead.com/spell={int(ability_id)}" target="_blank" '
                 f'style="color:inherit">{label}</a>')
    return f'<span class="ability-cell">{img}{label}{guide_button(guide, name)}</span>'


def guide_button(guide, name=''):
    """▶ opens the Mythic Trap clip; abilities without a clip get their tip as a hover ℹ️."""
    if not guide:
        return ''
    tip = guide.get('tip') or guide.get('description') or ''
    if guide.get('video_url'):
        return (f' <button class="clip-btn" data-embed="{esc(guide["embed_url"])}" '
                f'data-title="{esc(guide["name"] or name)}" data-tip="{esc(tip)}" '
                f'title="Watch how {esc(guide["name"] or name)} works">▶</button>')
    if tip:
        return f' <span class="guide-info" title="{esc(tip)}">ℹ️</span>'
    return ''


def tag_pill(tag, source=None):
    """source 'auto' = from the boss's Mythic Trap guide; 'manual' = set by an officer."""
    auto = ' <small style="opacity:.7">auto</small>' if source == 'auto' else ''
    why = ' (from the Mythic Trap guide)' if source == 'auto' else ' (set by an officer)'
    if tag == 'avoidable':
        return f'<span class="pill pill-avoidable" title="Every hit is a mistake{why}">avoidable{auto}</span>'
    if tag == 'avoidable_nontank':
        return (f'<span class="pill pill-avoidable" title="Avoidable for everyone except tanks{why}">'
                f'avoidable (non-tanks){auto}</span>')
    if tag == 'expected':
        return (f'<span class="pill pill-ignore" title="Part of the mechanic - soak, tankbuster or raid damage{why}">'
                f'expected{auto}</span>')
    if tag == 'ignore':
        return '<span class="pill pill-ignore">ignored</span>'
    return ''


def phase_label(pull, phase_names):
    phase = pull.get('last_phase')
    if not phase:
        return ''
    info = (phase_names or {}).get(str(pull['encounter_id']), {}).get(str(phase))
    if info:
        return esc(info['name'])
    return f"{'Intermission' if pull.get('last_phase_intermission') else 'Phase'} {phase}"


def result_pill(pull):
    if pull['kill']:
        return '<span class="pill pill-kill">✔ Kill</span>'
    return f'<span class="pill pill-wipe">{pull["fight_pct"] or 0:.1f}%</span>'


# ============================================================================
# Charts
# ============================================================================

def progress_chart(points, separators=()):
    """
    Boss % remaining per pull (0 = kill) with a best-so-far step line.

    points: [{'pct', 'kill', 'tip', 'href'}] in pull order.
    separators: [(index, label)] - vertical dividers (e.g. between raid nights).
    """
    if len(points) < 2:
        return ''  # a single pull says nothing a chart can show better than the table
    width, height = 900, 240
    left, right, top, bottom = 44, 16, 22, 26
    inner_w, inner_h = width - left - right, height - top - bottom
    n = len(points)

    def x(i):
        return left + (inner_w / 2 if n == 1 else i * inner_w / (n - 1))

    def y(pct):
        return top + inner_h * (1 - max(0.0, min(100.0, pct)) / 100)

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="Boss health remaining per pull">']
    for pct in (0, 25, 50, 75, 100):
        parts.append(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{y(pct):.1f}" y2="{y(pct):.1f}"/>'
                     f'<text x="{left - 8}" y="{y(pct) + 4:.1f}" text-anchor="end">{pct}%</text>')
    for index, label in separators:
        sx = (x(index - 1) + x(index)) / 2 if index > 0 else x(0)
        parts.append(f'<line class="grid" x1="{sx:.1f}" x2="{sx:.1f}" y1="{top}" y2="{top + inner_h}" '
                     f'stroke-dasharray="3 4"/>'
                     f'<text class="axis-label" x="{sx + 4:.1f}" y="{top - 8}">{esc(label)}</text>')

    pcts = [0.0 if p['kill'] else float(p['pct'] or 0) for p in points]
    line = ' '.join(f'{x(i):.1f},{y(v):.1f}' for i, v in enumerate(pcts))
    parts.append(f'<polyline points="{line}" fill="none" stroke="{SERIES_PULL}" stroke-width="2" '
                 f'stroke-linejoin="round" opacity="0.55"/>')
    best, step = 100.0, []
    for i, v in enumerate(pcts):
        if i:
            step.append(f'{x(i):.1f},{y(best):.1f}')
        best = min(best, v)
        step.append(f'{x(i):.1f},{y(best):.1f}')
    parts.append(f'<polyline points="{" ".join(step)}" fill="none" stroke="{SERIES_BEST}" '
                 f'stroke-width="2" stroke-linejoin="round"/>')

    for i, (point, v) in enumerate(zip(points, pcts)):
        color = STATUS_GOOD if point['kill'] else SERIES_PULL
        mark = (f'<circle class="mark" cx="{x(i):.1f}" cy="{y(v):.1f}" r="5" fill="{color}" '
                f'stroke="#161a2c" stroke-width="2"/>'
                f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="12" fill="transparent"/>'
                f'<title>{esc(point["tip"])}</title>')
        if point['kill']:
            mark += f'<text x="{x(i):.1f}" y="{y(v) - 10:.1f}" text-anchor="middle" fill="{STATUS_GOOD}">Kill</text>'
        if point.get('href'):
            mark = f'<a href="{esc(point["href"])}">{mark}</a>'
        parts.append(mark)
        if n <= 40 or i % max(1, n // 20) == 0:
            parts.append(f'<text x="{x(i):.1f}" y="{height - 8}" text-anchor="middle">{i + 1}</text>')
    parts.append('</svg>')

    legend = (f'<div class="legend" title="WCL fight %: how much of the encounter was left, accounting for '
              f'phases (0% = kill)"><span style="--c:{SERIES_PULL}">Fight % remaining (each pull)</span>'
              f'<span style="--c:{SERIES_BEST}">Best so far</span></div>')
    return legend + ''.join(parts)


def pull_timeline(pull, analysis, phase_names):
    """One pull on a time axis: phase bands, death ticks and the wipe moment."""
    duration = max(1, pull['end_ms'] - pull['start_ms'])
    width, height, left, right = 900, 74, 10, 10
    inner_w = width - left - right

    def x(t):
        return left + inner_w * max(0, min(t, duration)) / duration

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Pull timeline">']
    phases = pull.get('phases') or []
    names = (phase_names or {}).get(str(pull['encounter_id']), {})
    for i, phase in enumerate(phases):
        end = phases[i + 1]['start'] if i + 1 < len(phases) else duration
        shade = 0.10 if i % 2 == 0 else 0.05
        label = (names.get(str(phase['id'])) or {}).get('name') or f"Phase {phase['id']}"
        band = max(1, x(end) - x(phase['start']))
        fits = int((band - 12) / 6.2)  # ~6.2px per char at 11px
        short = label if len(label) <= fits else (label[:fits - 1] + '…' if fits >= 6 else '')
        parts.append(f'<rect x="{x(phase["start"]):.1f}" y="4" width="{band:.1f}" '
                     f'height="26" fill="rgba(255,255,255,{shade})"><title>{esc(label)} '
                     f'({fmt_duration(phase["start"])}–{fmt_duration(end)})</title></rect>')
        if short:
            parts.append(f'<text x="{x(phase["start"]) + 6:.1f}" y="21">{esc(short)}</text>')
    if not phases:
        parts.append(f'<rect x="{left}" y="4" width="{inner_w}" height="26" fill="rgba(255,255,255,0.08)"/>')

    for death in analysis.get('deaths') or []:
        color = 'rgba(255,255,255,0.3)' if death.get('after_wipe') else '#ff6b6b'
        parts.append(f'<line x1="{x(death["t"]):.1f}" x2="{x(death["t"]):.1f}" y1="34" y2="52" '
                     f'stroke="{color}" stroke-width="2"><title>{fmt_duration(death["t"])} '
                     f'{esc(death["name"])} died to {esc(death["ability"])}</title></line>'
                     f'<line x1="{x(death["t"]):.1f}" x2="{x(death["t"]):.1f}" y1="30" y2="56" '
                     f'stroke="transparent" stroke-width="8"><title>{fmt_duration(death["t"])} '
                     f'{esc(death["name"])} died to {esc(death["ability"])}</title></line>')
    end_label = f'<text x="{width - right}" y="68" text-anchor="end">{fmt_duration(duration)}</text>'
    if analysis.get('wipe_at') is not None:
        wx = x(analysis['wipe_at'])
        wipe_text = f'wipe called {fmt_duration(analysis["wipe_at"])}'
        if wx > width - right - 150:  # too close to the end label - fold it in
            wipe_text += f' of {fmt_duration(duration)}'
            end_label = ''
        parts.append(f'<line x1="{wx:.1f}" x2="{wx:.1f}" y1="2" y2="58" stroke="#ffd43b" stroke-width="2" '
                     f'stroke-dasharray="4 3"/><text x="{min(wx, width - right):.1f}" y="68" text-anchor="end" '
                     f'fill="#ffd43b">{wipe_text}</text>')
    parts.append(f'<text x="{left}" y="68">0:00</text>{end_label}</svg>')
    return ''.join(parts)


# ============================================================================
# Tables
# ============================================================================

def scoreboard_table(rows, show_avoidable=True):
    if not rows:
        return '<p class="muted">No players.</p>'
    head = ('<tr><th data-sort>Player</th><th data-sort class="num">Pulls</th>'
            '<th data-sort class="num" title="Deaths before the wipe was called">Deaths</th>'
            '<th data-sort class="num" title="First player to die in a pull">First death</th>'
            '<th data-sort class="num" title="Share of pull time alive (until wipe called)">Alive %</th>')
    if show_avoidable:
        head += ('<th data-sort class="num" title="Hits from abilities tagged avoidable">Avoidable hits</th>'
                 '<th data-sort class="num">Avoidable dmg</th>')
    head += ('<th data-sort class="num">Interrupts</th><th data-sort class="num">Dispels</th>'
             '<th data-sort class="num" title="Pulls with at least one combat or mana potion used during the pull">'
            'Potion pulls</th>'
             '<th data-sort class="num" title="Healthstones + healing potions">Healthstones</th></tr>')
    body = []
    for r in rows:
        alive = 100 * r['alive_ms'] / r['pull_ms'] if r['pull_ms'] else 100
        potion_share = r['potion_pulls'] / r['pulls'] if r['pulls'] else 0
        cells = [f'<td data-v="{esc(r["name"])}">{player_name(r["name"], r["class"], r["role"])}</td>',
                 f'<td class="num">{r["pulls"]}</td>',
                 f'<td class="num{" bad" if r["deaths"] and r["deaths"] >= max(2, r["pulls"] / 2) else ""}">'
                 f'{r["deaths"]}</td>',
                 f'<td class="num{" bad" if r["first_deaths"] >= 2 else ""}">{r["first_deaths"]}</td>',
                 f'<td class="num" data-v="{alive:.1f}">{alive:.0f}%</td>']
        if show_avoidable:
            cells += [f'<td class="num{" bad" if r["avoidable_hits"] else ""}">{r["avoidable_hits"]}</td>',
                      f'<td class="num" data-v="{r["avoidable_damage"]}">{fmt_amount(r["avoidable_damage"])}</td>']
        cells += [f'<td class="num">{r["interrupts"] or ""}</td>',
                  f'<td class="num">{r["dispels"] or ""}</td>',
                  f'<td class="num{" bad" if potion_share < 0.5 else ""}" data-v="{r["potion_pulls"]}">'
                  f'{r["potion_pulls"]}/{r["pulls"]}</td>',
                  f'<td class="num">{r["defensives"] or ""}</td>']
        body.append(f'<tr>{"".join(cells)}</tr>')
    return f'<div class="table-wrapper"><table class="compact">{head}{"".join(body)}</table></div>'


def killers_table(rows, limit=8, guide_for=lambda ability_id, name: None):
    if not rows:
        return '<p class="muted">Nobody died before a wipe was called. 🎉</p>'
    body = ''.join(
        f'<tr><td>{ability(k["name"], k["icon"], k["id"], guide_for(k["id"], k["name"]))}</td><td class="num">{k["count"]}</td>'
        f'<td class="small">{", ".join(f"{esc(n)}" + (f" ×{c}" if c > 1 else "") for n, c in sorted(k["players"].items(), key=lambda kv: -kv[1]))}</td></tr>'
        for k in rows[:limit])
    return (f'<div class="table-wrapper"><table class="compact"><tr><th>Killed by</th><th class="num">Deaths</th>'
            f'<th>Who</th></tr>{body}</table></div>')


def tag_buttons(encounter_id, difficulty, ability_id, ability_name, current, source, back):
    """
    Avoidable / Non-tanks / Ignore toggles; clicking the active one clears the tag.
    Any click is an officer override; ↺ drops the override and returns to the automatic tag.
    """
    buttons = []
    for tag, label, hint in (('avoidable', 'Avoidable', 'Every hit is a mistake'),
                             ('avoidable_nontank', 'Non-tanks', 'A mistake for everyone except tanks'),
                             ('ignore', 'Ignore', 'Hide from the damage tables')):
        on = current == tag
        buttons.append(f'<button name="tag" value="{"none" if on else tag}" '
                       f'class="{"on-" + tag if on else ""}" title="{"Clear tag" if on else hint}">'
                       f'{label}</button>')
    if source == 'manual':
        buttons.append('<button name="tag" value="auto" title="Undo your override and use the automatic tag">'
                       '↺ auto</button>')
    return (f'<form method="post" action="/admin/raids/boss/{encounter_id}/{difficulty}/tag" class="tag-form">'
            f'<input type="hidden" name="ability_id" value="{ability_id}">'
            f'<input type="hidden" name="ability_name" value="{esc(ability_name)}">'
            f'<input type="hidden" name="back" value="{esc(back)}">{"".join(buttons)}</form>')


# ============================================================================
# Overall view / mechanics list building blocks
# ============================================================================

def deaths_strip(rows):
    """
    Every pull of a boss on one time axis: a bar per pull (its length), phase
    changes, death ticks (red before the wipe call, grey after) and the wipe call.
    rows: [{'label', 'href', 'duration', 'phases': [ms], 'deaths': [...], 'wipe_at', 'kill'}]
    """
    if not rows:
        return ''
    row_h, left, right, top = 22, 118, 12, 8
    width = 900
    longest = max(r['duration'] for r in rows) or 1
    inner_w = width - left - right
    height = top + row_h * len(rows) + 22

    def x(t):
        return left + inner_w * max(0, min(t, longest)) / longest

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Deaths in every pull">']
    for minute in range(0, int(longest / 60000) + 1):
        mx = x(minute * 60000)
        parts.append(f'<line class="grid" x1="{mx:.1f}" x2="{mx:.1f}" y1="{top}" y2="{height - 18}"/>'
                     f'<text x="{mx:.1f}" y="{height - 4}" text-anchor="middle">{minute}:00</text>')
    for i, r in enumerate(rows):
        y = top + i * row_h
        bar = (f'<rect x="{left}" y="{y + 4}" width="{max(2, x(r["duration"]) - left):.1f}" height="{row_h - 8}" '
               f'rx="3" fill="{"rgba(81,207,102,0.25)" if r["kill"] else "rgba(255,255,255,0.08)"}"/>')
        for start in r['phases']:
            bar += (f'<line x1="{x(start):.1f}" x2="{x(start):.1f}" y1="{y + 3}" y2="{y + row_h - 3}" '
                    f'stroke="rgba(255,255,255,0.35)" stroke-width="1"/>')
        for d in r['deaths']:
            color = 'rgba(255,255,255,0.35)' if d.get('after_wipe') else '#ff6b6b'
            bar += (f'<line x1="{x(d["t"]):.1f}" x2="{x(d["t"]):.1f}" y1="{y + 5}" y2="{y + row_h - 5}" '
                    f'stroke="{color}" stroke-width="2"><title>{fmt_duration(d["t"])} {esc(d["name"])} '
                    f'died to {esc(d["ability"])}</title></line>')
        if r.get('wipe_at') is not None:
            bar += (f'<line x1="{x(r["wipe_at"]):.1f}" x2="{x(r["wipe_at"]):.1f}" y1="{y + 2}" y2="{y + row_h - 2}" '
                    f'stroke="#ffd43b" stroke-width="2" stroke-dasharray="3 2"><title>Wipe called '
                    f'{fmt_duration(r["wipe_at"])}</title></line>')
        parts.append(f'<a href="{esc(r["href"])}"><rect x="0" y="{y}" width="{width}" height="{row_h}" fill="transparent"/>'
                     f'<text x="{left - 10}" y="{y + row_h / 2 + 4:.1f}" text-anchor="end">{esc(r["label"])}</text>{bar}</a>')
    parts.append('</svg>')
    return ''.join(parts)


def bar_table(rows, value_head='', note_head=''):
    """
    Horizontal bars, one per row: [(label_html, value, value_text, note_html)].
    A single series, so no legend - the value is printed beside each bar.
    """
    if not rows:
        return '<p class="muted small">Nothing to show.</p>'
    top = max((r[1] for r in rows), default=0) or 1
    body = ''.join(
        f'<tr><td>{label}</td><td class="bar-cell"><div class="bar" style="width:{max(2, 100 * value / top):.1f}%"></div></td>'
        f'<td class="num">{text}</td>{f"<td class=small>{note}</td>" if note_head else ""}</tr>'
        for label, value, text, note in rows)
    head = (f'<tr><th></th><th></th><th class="num">{esc(value_head)}</th>'
            f'{f"<th>{esc(note_head)}</th>" if note_head else ""}</tr>')
    return f'<div class="table-wrapper"><table class="compact bars">{head}{body}</table></div>'


def hit_timeline(rows, duration, phases=()):
    """
    One pull: when each player got hit. rows: [(name, [ms, ...])], phases: [ms].
    Dots on a shared time axis; hover a dot for the exact time.
    """
    if not rows:
        return ''
    row_h, left, right, top = 20, 118, 12, 6
    width = 900
    inner_w = width - left - right
    height = top + row_h * len(rows) + 22
    duration = max(duration, 1)

    def x(t):
        return left + inner_w * max(0, min(t, duration)) / duration

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Hit timeline">']
    for start in phases:
        parts.append(f'<line class="grid" x1="{x(start):.1f}" x2="{x(start):.1f}" y1="{top}" y2="{height - 18}" '
                     f'stroke-dasharray="3 3"/>')
    for i, (name, times) in enumerate(rows):
        y = top + i * row_h + row_h / 2
        parts.append(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}"/>'
                     f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end">{esc(name)}</text>')
        for t in times:
            parts.append(f'<circle cx="{x(t):.1f}" cy="{y:.1f}" r="4.5" fill="{SERIES_PULL}" stroke="#161a2c" '
                         f'stroke-width="1.5"><title>{esc(name)} — {fmt_duration(t)}</title></circle>')
    parts.append(f'<text x="{left}" y="{height - 4}">0:00</text>'
                 f'<text x="{width - right}" y="{height - 4}" text-anchor="end">{fmt_duration(duration)}</text></svg>')
    return ''.join(parts)


def per_pull_columns(values, label='per pull'):
    """Small column chart: one column per pull number. values: [(pull_number, value)]."""
    if len(values) < 2:
        return ''
    width, height, left, bottom, top = 900, 120, 36, 20, 14
    top_value = max(v for _, v in values) or 1
    step = (width - left - 10) / len(values)
    bar_w = max(4, min(28, step - 2))
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(label)}">',
             f'<line class="grid" x1="{left}" x2="{width - 10}" y1="{height - bottom}" y2="{height - bottom}"/>']
    for i, (number, value) in enumerate(values):
        h = (height - bottom - top) * value / top_value
        cx = left + step * i + step / 2
        parts.append(f'<rect x="{cx - bar_w / 2:.1f}" y="{height - bottom - h:.1f}" width="{bar_w:.1f}" '
                     f'height="{max(h, 0.5):.1f}" rx="3" fill="{SERIES_PULL}"><title>Pull {number}: {value}</title></rect>'
                     f'<text x="{cx:.1f}" y="{height - 5}" text-anchor="middle">{number}</text>')
        if value and (len(values) <= 24 or value == top_value):
            parts.append(f'<text x="{cx:.1f}" y="{height - bottom - h - 4:.1f}" text-anchor="middle">{value}</text>')
    parts.append('</svg>')
    return ''.join(parts)


def phase_funnel(phases, total):
    """How many pulls reached each phase, with when they got there and how long they stayed."""
    if not phases:
        return ''
    rows = []
    for ph in phases:
        share = ph['reached'] / total if total else 0
        rows.append(
            f'<tr><td>{esc(ph["name"])}</td>'
            f'<td class="bar-cell"><div class="bar" style="width:{max(2, 100 * share):.1f}%"></div></td>'
            f'<td class="num">{ph["reached"]}/{total}</td>'
            f'<td class="num small muted" title="Average / best time into the pull this phase started">'
            f'{fmt_duration(ph["avg_entry"])} <span class="muted">(best {fmt_duration(ph["best_entry"])})</span></td>'
            f'<td class="num small muted">{fmt_duration(ph["avg_time"])}</td></tr>')
    return (f'<div class="table-wrapper"><table class="compact bars"><tr><th>Phase</th><th></th>'
            f'<th class="num">Pulls reached</th><th class="num">Reached at</th><th class="num">Avg. time in phase</th></tr>'
            f'{"".join(rows)}</table></div>')


def phase_heatmap(nights, phase_order):
    """
    Nights x phases: share of each night's pulls that reached each phase.
    Single-hue sequential shading (darker = more pulls got there); the number is printed in every cell.
    nights: [(label_html, {phase_id: reached}, total_pulls)]; phase_order: [(phase_id, name)].
    """
    if not nights or not phase_order:
        return ''
    head = ''.join(f'<th class="num" title="{esc(name)}">{esc(name.split(":")[0])}</th>' for _, name in phase_order)
    rows = []
    for label, reached, total in nights:
        cells = []
        for phase_id, _ in phase_order:
            n = reached.get(phase_id, 0)
            share = n / total if total else 0
            cells.append(f'<td class="num heat" style="--a:{0.08 + 0.72 * share:.2f}" '
                         f'title="{n} of {total} pulls">{n}<small>/{total}</small></td>')
        rows.append(f'<tr><td>{label}</td>{"".join(cells)}</tr>')
    return (f'<div class="table-wrapper"><table class="compact heatmap"><tr><th>Night</th>{head}</tr>'
            f'{"".join(rows)}</table></div>')


def sparkline(values, low=0, high=100):
    """Tiny single-series line (e.g. a player's score per night) - the last point is marked."""
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return ''
    width, height, pad = 120, 28, 4
    step = (width - 2 * pad) / (len(values) - 1)

    def y(v):
        return height - pad - (height - 2 * pad) * (max(low, min(high, v)) - low) / ((high - low) or 1)

    points = ' '.join(f'{pad + i * step:.1f},{y(v):.1f}' for i, v in enumerate(values))
    return (f'<svg class="spark" viewBox="0 0 {width} {height}" aria-hidden="true">'
            f'<polyline points="{points}" fill="none" stroke="{SERIES_PULL}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{pad + (len(values) - 1) * step:.1f}" cy="{y(values[-1]):.1f}" r="3" fill="{SERIES_PULL}"/></svg>')
