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
td.good-text { font-weight: 600; }
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
/* Sections: every card opens with a header (sec-head, or a plain h2 styled alike); parts inside a
   card are sub-sections with their own divider + label - nothing runs into the next thing. */
.card { margin-bottom: 20px; }
.card > h2:first-child { padding-bottom: 14px; margin-bottom: 18px; border-bottom: 1px solid var(--border); }
.sec-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px;
    padding-bottom: 16px; margin-bottom: 18px; border-bottom: 1px solid var(--border); }
.sec-title { display: flex; gap: 14px; align-items: flex-start; min-width: 0; }
.sec-title h2 { margin: 0; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.sec-icon { flex: none; width: 38px; height: 38px; border-radius: 11px; display: inline-flex; align-items: center;
    justify-content: center; font-size: 19px; background: var(--surface-3); border: 1px solid var(--border); }
.sec-sub { margin: 5px 0 0; color: var(--muted); font-size: 13px; line-height: 1.55; max-width: 900px; }
.sec-action { flex: none; display: flex; gap: 8px; align-items: center; }
.sub { margin-top: 26px; padding-top: 20px; border-top: 1px solid var(--border); }
.sub:first-child, .sec-head + .sub { margin-top: 0; padding-top: 0; border-top: 0; }
.sub-title { margin: 0 0 12px; font-size: 12px; font-weight: 650; letter-spacing: .07em; text-transform: uppercase;
    color: var(--faint); }
.sub-caption { margin: 8px 0 0; color: var(--faint); font-size: 12px; }
.stat-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 22px; }
.stat-tile { background: var(--surface-2); border: 1px solid var(--border); border-radius: 12px; padding: 12px 16px; }
.stat-tile b { display: block; font-size: 22px; font-weight: 700; letter-spacing: -0.01em; color: var(--text); }
.stat-tile span { display: block; margin-top: 2px; font-size: 11px; font-weight: 600; letter-spacing: .06em;
    text-transform: uppercase; color: var(--faint); }
/* Player page sections (Execution / Damage & focus / Cooldowns / Rotation) */
.ptabs { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 18px; }
.ptab { display: inline-flex; align-items: center; gap: 8px; padding: 9px 16px; border-radius: 10px;
    border: 1px solid var(--border); background: var(--surface); color: var(--muted); font-weight: 600; font-size: 14px; }
.ptab:hover { color: var(--text); border-color: var(--border-strong); text-decoration: none; }
.ptab.active { color: #fff; background: var(--accent-soft); border-color: var(--accent); }
/* WowAnalyzer-style stat tiles: rotation (casts / min) and uptime */
.rot-tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; }
.rot-tile { background: var(--surface-2); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px;
    display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.rot-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; font-weight: 600; font-size: 14px; }
.rot-head .cmp-ab, .rot-head .ability-cell { min-width: 0; overflow-wrap: anywhere; }
.rot-head .pill { flex-shrink: 0; }
.rot-value b { font-size: 24px; font-weight: 700; letter-spacing: -0.01em; }
.rot-value span { margin-left: 6px; font-size: 12px; color: var(--faint); }
.uptime-strip { position: relative; height: 10px; border-radius: 3px; background: var(--surface-3); overflow: hidden; }
.uptime-strip i { position: absolute; top: 0; bottom: 0; background: var(--accent); opacity: .85; }
.kind-select { font: inherit; font-size: 11px; padding: 1px 4px; background: var(--surface-3); color: var(--muted);
    border: 1px solid var(--border); border-radius: 6px; }
.parse { font-weight: 700; }
.parse.p100 { color: #e5cc80; } .parse.p99 { color: #e268a8; } .parse.p95 { color: #ff8000; }
.parse.p75 { color: #a335ee; } .parse.p50 { color: #0070ff; } .parse.p25 { color: #1eff00; } .parse.p0 { color: #9d9d9d; }
.focus-bar { display: flex; height: 8px; border-radius: 3px; overflow: hidden; background: var(--surface-3); min-width: 120px; }
.focus-bar i { display: block; height: 100%; }
@media (max-width: 600px) {
    .sec-head { flex-direction: column; }
    .sec-icon { width: 32px; height: 32px; font-size: 16px; }
}
/* Compact players table (Mechanics tab) */
tr.click-row { cursor: pointer; }
tr.click-row:hover td { background: var(--surface-2); }
.plain-link { color: inherit; }
.plain-link:hover { text-decoration: none; }
.score-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 40px; height: 28px;
    padding: 0 8px; border-radius: 8px; font-weight: 700; font-variant-numeric: tabular-nums; }
.score-badge.good { background: var(--good-soft); color: var(--good); }
.score-badge.ok { background: var(--warn-soft); color: var(--warn); }
.score-badge.bad { background: var(--bad-soft); color: var(--bad); }
.sub-val { font-weight: 600; font-variant-numeric: tabular-nums; }
.sub-val.good { color: var(--good); } .sub-val.ok { color: var(--warn); } .sub-val.bad { color: var(--bad); }
.tip-cell { max-width: 380px; }
.tip-line { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; color: #ffcfc7; }
/* Mechanics table: filter chips + expandable rows */
.mech-wrap .tl-chips { margin-bottom: 10px; }
tr.mech-row { cursor: pointer; }
tr.mech-row:hover td { background: var(--surface-2); }
tr.mech-row.open td { background: var(--accent-soft); }
.mech-caret { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px;
    margin-right: 8px; vertical-align: middle; border-radius: 50%; border: 1px solid var(--border-strong);
    background: var(--surface-3); color: var(--text); transition: transform .15s, background .15s, border-color .15s; }
.mech-caret svg { width: 12px; height: 12px; }
tr.mech-row:hover .mech-caret { border-color: var(--accent); color: #fff; }
tr.mech-row.open .mech-caret { transform: rotate(90deg); background: var(--accent); border-color: var(--accent); color: #fff; }
tr.mech-detail > td { background: var(--surface-2); padding: 12px 16px 16px; }
.mech-detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px 24px; }
.mech-detail-grid h4 { margin: 0 0 6px; }
.mech-detail-grid .mech-wide { grid-column: 1 / -1; }
/* Compare-with-top-players page (web/compare.py) */
.top-list { margin: 8px 0 0 18px; padding: 0; font-size: 13px; line-height: 1.7; }
details.top-players > summary { cursor: pointer; color: var(--accent); margin: 4px 0; }
.notes { list-style: none; margin: 8px 0 14px; padding: 0; }
.notes li { padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 14px; }
.notes li:last-child { border-bottom: 0; }
.cmp-ab { display: inline-flex; align-items: center; gap: 6px; }
.cmp-ab .ability-icon { width: 18px; height: 18px; }
tr.muted-row td { opacity: 0.7; }
.cmp-tl { --label-w: 190px; }
.cmp-tl .tl-body { grid-template-columns: var(--label-w) minmax(0, 1fr); }
.cmp-tl .tl-scroll { padding: 0 10px; }
.cmp-tl .tl-lab { height: 20px; font-size: 12px; color: var(--muted); }
.cmp-tl .tl-lab.you { color: var(--text); font-weight: 600; }
.cmp-tl .tl-lab.grp { height: 26px; justify-content: space-between; padding-left: 4px; color: var(--text);
    font-weight: 600; box-shadow: inset 0 1px rgba(255,255,255,0.15); }
.cmp-tl .tl-lab.grp .pill { font-size: 10px; padding: 1px 7px; }
.cmp-tl .grp-right { display: inline-flex; align-items: center; gap: 6px; }
/* ability headers: name on one line, this pull's count + the verdict under it (the label column is narrow) */
.cmp-tl .tl-lab.grp:not([data-g="boss"]), .cmp-tl .tl-row.grp:not([data-g="boss"]) { height: 44px; }
.cmp-tl .tl-lab.grp:not([data-g="boss"]) { flex-direction: column; align-items: flex-start; justify-content: center;
    gap: 3px; }
.cmp-tl .tl-lab.grp .cmp-ab { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cmp-tl .pull-score { font-size: 10px; font-weight: 600; color: var(--muted); white-space: nowrap; }
.cmp-tl .tl-row { height: 20px; }
.cmp-tl .tl-row.grp { height: 26px; box-shadow: inset 0 1px rgba(255,255,255,0.15); }
.cmp-tl .tl-row.you { background: rgba(116,132,236,0.10); }
.cmp-tl .tl-lab.boss, .cmp-tl .tl-row.boss { height: 16px; }
.cmp-tl .tl-lab.boss { font-size: 11px; font-weight: 400; }
.cmp-tl .tl-lab.boss .ability-icon { width: 13px; height: 13px; }
.cmp-tl .m.cd { width: 16px; height: 16px; }
.cmp-tl .win { position: absolute; top: 4px; bottom: 4px; border-radius: 4px; background: rgba(255,212,59,0.16);
    border: 1px solid rgba(255,212,59,0.35); }
.cmp-tl .win.weak { background: rgba(255,107,107,0.16); border-color: rgba(255,107,107,0.55); }
.pill-mostly { background: rgba(252,196,25,0.16); color: #ffd43b; }
.pill-muted { background: var(--surface-3); color: var(--muted); font-weight: 500; }
.weak-line { margin: 3px 0 0 24px; font-size: 12px; color: #ffb4a8; }
.cmp-tl .ph { position: absolute; top: 2px; bottom: 2px; border-left: 1px dashed rgba(255,255,255,0.35); }
.cmp-tl.real .al, .cmp-tl:not(.real) .rl, .cmp-tl.real .win { display: none; }
.tl-chip .chip-icon { width: 16px; height: 16px; border-radius: 3px; }
.seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin-right: auto; }
.seg button { border: 0; border-radius: 0; padding: 4px 10px; background: transparent; color: var(--muted);
    font: inherit; font-size: 12px; cursor: pointer; }
.seg button[aria-pressed=true] { background: var(--surface-3); color: var(--text); }
.seg ~ .muted { margin-right: 0 !important; }
@media (max-width: 600px) { .cmp-tl { --label-w: 120px; } }
/* Consumables timeline toggles (consumables.toolbar) */
.tl-chips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 4px 0 8px; }
.tl-chip, .tl-pick summary { display: inline-flex; align-items: center; gap: 6px; padding: 4px 11px; border-radius: 999px;
    border: 1px solid var(--border); background: transparent; color: var(--muted); font: inherit; font-size: 12px;
    cursor: pointer; list-style: none; }
.tl-chip:hover, .tl-pick summary:hover { color: var(--text); }
.tl-chip[aria-pressed=true] { background: var(--surface-3); color: var(--text); border-color: var(--border-strong); }
.tl-chip.partial { color: var(--text); border-style: dashed; border-color: var(--border-strong); }
.tl-chip i, .tl-static i { display: inline-block; width: 12px; height: 4px; border-radius: 2px; background: var(--c); }
.tl-chip[aria-pressed=false] i { opacity: 0.35; }
.tl-static { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); margin-left: 6px; }
.tl-pick summary::-webkit-details-marker { display: none; }
.tl-pick[open] { flex-basis: 100%; }
.tl-pick[open] summary { color: var(--text); border-color: var(--border-strong); }
/* The picker is a button, not another chip: accent-tinted so it's found without looking for it */
.tl-pick summary { background: color-mix(in srgb, var(--accent) 22%, transparent); border-color: var(--accent);
    color: var(--text); font-weight: 600; }
.tl-pick summary:hover { background: color-mix(in srgb, var(--accent) 34%, transparent); }
.tl-pick[open] summary { background: var(--accent); border-color: var(--accent); color: #fff; }
.tl-pick-menu { margin-top: 8px; padding: 12px 14px; border: 1px solid var(--border); border-radius: 10px;
    background: var(--surface-2, rgba(255,255,255,0.03)); display: grid; gap: 10px 22px;
    grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); }
.tl-pick-menu h5 { margin: 0 0 6px; font-size: 12px; font-weight: 600; color: var(--muted); }
.tl-pick-menu label { display: flex; align-items: center; gap: 6px; padding: 2px 0; font-size: 12px; cursor: pointer; }
.tl-pick-menu .ability-icon { width: 16px; height: 16px; }
/* Editor-style zoomable timeline (deaths_strip) */
.tl { margin: 6px 0 18px; }
.tl-tools { display: flex; align-items: center; justify-content: flex-end; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }
.tl-tools .muted { margin-right: auto; }
.tl-tools button { min-width: 30px; padding: 3px 9px; border-radius: 7px; border: 1px solid var(--border);
    background: transparent; color: var(--muted); cursor: pointer; font: inherit; font-size: 12px; }
.tl-tools button:hover { color: var(--text); border-color: var(--border-strong); }
.tl-tools input[type=range] { width: 140px; accent-color: #7484ec; }
@media (pointer: coarse), (max-width: 600px) { .tl-tools .muted { display: none; } }
.tl-body { display: grid; grid-template-columns: 118px minmax(0, 1fr); }
.tl-labels a { display: flex; align-items: center; justify-content: flex-end; padding-right: 10px;
    font-size: 11px; color: var(--muted); text-decoration: none; white-space: nowrap; overflow: hidden; }
.tl-labels a:hover { color: var(--text); }
.tl-ruler-gap { height: 20px; }
.tl-scroll { overflow-x: auto; overflow-y: hidden; scrollbar-width: thin; }
.tl-inner { position: relative; width: 100%; }
.tl-track { display: block; width: 100%; }
.tl-track * { vector-effect: non-scaling-stroke; }
.tl-track .grid { stroke: rgba(255,255,255,0.06); }
.tl-track .tl-hit { fill: transparent; }
.tl-track a:hover .tl-hit { fill: rgba(255,255,255,0.04); }
.tl-track .tl-hit-line { stroke: transparent; stroke-width: 12; }
.tl-track .tl-mark { cursor: help; }
.warn-text { color: #ffd43b; }
.full-budget { display: inline-flex; align-items: center; gap: 5px; margin-left: 6px; cursor: pointer; }
.ability-cell[data-spell] { cursor: help; }
.tl-track .tl-mark:hover line:first-child { stroke: #fff; }
.tl-ruler { position: relative; height: 20px; font-size: 11px; color: var(--muted); }
.tl-ruler span { position: absolute; top: 4px; transform: translateX(-50%); white-space: nowrap; }
.tl-ruler span.first { transform: none; }
.tl-head { position: absolute; top: 0; bottom: 20px; border-left: 1px solid rgba(255,255,255,0.6); pointer-events: none; }
.tl-head span { position: absolute; top: 100%; transform: translateX(-50%); margin-top: 2px; padding: 0 5px;
    border-radius: 4px; background: #2a2f45; color: var(--text); font-size: 11px; white-space: nowrap; }
.tl-scroll { cursor: grab; }
.tl.dragging .tl-scroll { cursor: grabbing; user-select: none; }
.tl [hidden] { display: none !important; }
/* HTML timeline (consumables): rows of absolutely placed marks, positioned in % of the track */
.cons-tl { --label-w: 150px; }
.cons-tl .tl-body { grid-template-columns: var(--label-w) minmax(0, 1fr); }
.cons-tl .tl-scroll { padding: 0 10px; }  /* room for marks right at the start / end of the pull */
.tl-lab { height: 22px; display: flex; align-items: center; justify-content: flex-end; gap: 6px; padding-right: 10px;
    font-size: 12px; white-space: nowrap; overflow: hidden; }
.tl-lab span { overflow: hidden; text-overflow: ellipsis; }
.tl-lab.boss { height: 16px; font-size: 11px; color: var(--muted); cursor: help; }
.tl-lab.boss .ability-icon { width: 13px; height: 13px; }
.tl-row { position: relative; height: 22px; }
.tl-row.boss { height: 16px; }
.tl-row:not(.boss)::before { content: ''; position: absolute; left: 0; right: 0; top: 50%;
    border-top: 1px solid rgba(255,255,255,0.06); }
.tl-lab.sep, .tl-row.sep { box-shadow: inset 0 1px rgba(255,255,255,0.15); }
.tl-grid { position: absolute; inset: 0 0 20px 0; pointer-events: none; }
.tl-grid i, .tl-phase { position: absolute; top: 0; bottom: 0; border-left: 1px solid rgba(255,255,255,0.06); }
.tl-phase { bottom: 20px; border-left: 1px dashed rgba(255,255,255,0.3); pointer-events: none; }
.focus-tl .tl-phase.fspawnline { border-left: 2px dashed var(--c); opacity: 0.85; z-index: 1; }
.tl .m { position: absolute; top: 50%; transform: translate(-50%, -50%); }
.tl .m:hover { z-index: 3; }
.m.tick { width: 2px; height: 10px; background: #9aa1b9; border-radius: 1px; }
.m.tick::after { content: ''; position: absolute; inset: -3px -4px; }
.m.tick:hover { background: #fff; }
.m.bar { height: 10px; min-width: 3px; border-radius: 3px; transform: translateY(-50%); }
.m.k-potion { background: var(--potion); }
.m.k-mana { background: var(--mana); }
.m.dia { width: 9px; height: 9px; background: var(--defensive); transform: translate(-50%, -50%) rotate(45deg);
    box-shadow: 0 0 0 1.5px var(--surface); }
.m.death { font-size: 13px; font-weight: 700; line-height: 1; color: rgba(255,255,255,0.4); font-style: normal; }
.m.death.early { color: #ff6b6b; }
.m.cd { width: 16px; height: 16px; border-radius: 4px; background-color: var(--surface); background-size: cover;
    box-shadow: 0 0 0 1.5px var(--surface); }
.m.cd:hover, .m.dia:hover, .m.bar:hover { box-shadow: 0 0 0 1.5px #fff; }
/* Focus timeline (focusview.py): its own panel; groups with headers; per target a raid track over a you track */
.focus-tl { background: var(--surface-2); border: 1px solid var(--border); border-radius: 12px;
    padding: 12px 14px 6px; margin: 12px 0 18px; }
.focus-tl .tl-body { grid-template-columns: 210px minmax(0, 1fr); }
.focus-tl .tl-scroll { padding: 0 10px; }
.focus-tl .tl-row::before { display: none; }
.focus-tl .tl-lab.fgrp, .focus-tl .tl-row.fgrp { height: 46px; }
.focus-tl .tl-lab.fgrp { flex-direction: column; align-items: flex-start; justify-content: flex-end; gap: 1px;
    padding: 0 0 5px 2px; white-space: normal; }
.focus-tl .tl-lab.fgrp b { font-size: 12px; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text); }
.focus-tl .tl-lab.fgrp small { font-size: 11px; color: var(--faint); max-width: 100%; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }
.focus-tl .tl-row.fgrp { border-bottom: 1px solid rgba(255,255,255,0.12); }
.focus-tl .tl-lab.f-boss, .focus-tl .tl-row.f-boss { height: 22px; }
.focus-tl .tl-lab.f-boss { font-size: 12px; }
.focus-tl .tl-lab.f-boss .ability-icon { width: 16px; height: 16px; }
.focus-tl .tl-row.f-boss { border-bottom: 1px solid rgba(255,255,255,0.04); }
.focus-tl .m.tick { height: 14px; width: 3px; }
.focus-tl .tl-lab.f-ribbon, .focus-tl .tl-row.f-ribbon { height: 40px; }
.focus-tl .tl-lab.f-ribbon { font-weight: 600; color: var(--text); font-size: 13px; }
.frun { position: absolute; top: 8px; bottom: 8px; min-width: 2px; background: var(--c); cursor: help;
    box-shadow: inset -1px 0 var(--surface-2); }
.frun:hover, .fyou:hover, .fraid:hover { filter: brightness(1.3); }
.focus-tl .tl-lab.f-target, .focus-tl .tl-row.f-target { height: 52px; }
.focus-tl .tl-row.f-target.alt, .focus-tl .tl-lab.f-target.alt { background: rgba(255,255,255,0.025); }
.focus-tl .tl-lab.f-target { justify-content: space-between; padding-left: 2px; color: var(--text); font-size: 13px; }
.flab { display: flex; align-items: center; gap: 6px; min-width: 0; }
.flab > span { overflow: hidden; text-overflow: ellipsis; }
.flab .pill { font-size: 10px; padding: 1px 6px; flex-shrink: 0; }
.fsides { display: flex; flex-direction: column; gap: 6px; align-items: flex-end; flex-shrink: 0; padding-left: 6px; }
.fsides small { font-size: 10px; line-height: 14px; color: var(--faint); text-transform: uppercase; letter-spacing: 0.04em; }
.flane { position: absolute; inset: 0; }
.fraid { position: absolute; top: 8px; height: 14px; border-radius: 3px; cursor: help;
    background: color-mix(in srgb, var(--c) 22%, transparent); }
.fraid.prio { background: color-mix(in srgb, var(--c) 35%, transparent); box-shadow: inset 0 0 0 1.5px var(--c); }
.fyou { position: absolute; bottom: 8px; height: 16px; border-radius: 3px; min-width: 2px; background: var(--c); cursor: help; }
.focus-tl .tl-lab.f-phase, .focus-tl .tl-row.f-phase { height: 28px; }
.focus-tl .tl-lab.f-adds, .focus-tl .tl-row.f-adds { height: 34px; }
.focus-tl .tl-lab.f-phase, .focus-tl .tl-lab.f-adds { color: var(--text); font-weight: 600; }
.focus-tl .tl-phase { border-left: 1px dashed rgba(255,255,255,0.4); }
.fphase { position: absolute; top: 4px; bottom: 4px; background: rgba(116,132,236,0.18); border-radius: 3px;
    box-shadow: inset 1px 0 rgba(255,255,255,0.35); overflow: hidden; cursor: help; }
.fphase.alt { background: rgba(116,132,236,0.30); }
.fphase.inter { background: repeating-linear-gradient(135deg, rgba(201,133,0,0.25) 0 6px, rgba(201,133,0,0.12) 6px 12px); }
.fphase span { position: absolute; left: 6px; top: 50%; transform: translateY(-50%); font-size: 11px; font-weight: 600;
    color: var(--text); white-space: nowrap; }
.fev { position: absolute; top: 50%; transform: translate(-50%, -50%); width: 16px; height: 16px; border-radius: 4px;
    background: var(--c); color: #fff; font-size: 9px; font-style: normal; line-height: 16px; text-align: center;
    cursor: help; z-index: 1; }
.fev.out { background: var(--surface-3); color: var(--c); box-shadow: inset 0 0 0 1.5px var(--c); }
.fev.died { background: var(--surface-3); color: var(--bad); box-shadow: inset 0 0 0 1.5px var(--bad); }
.fev.prio { box-shadow: 0 0 0 2px var(--surface-2), 0 0 0 3.5px var(--c); }
.fev span { position: absolute; left: 20px; top: 50%; transform: translateY(-50%); font-size: 11px; font-weight: 600;
    color: var(--text); white-space: nowrap; pointer-events: none; }
.fev:hover { filter: brightness(1.3); z-index: 3; }
.flead { position: absolute; top: 3px; height: 9px; border: 2px solid var(--c); border-bottom: 0;
    border-radius: 3px 3px 0 0; cursor: help; z-index: 2; }
.flead span { position: absolute; left: 50%; top: -1px; transform: translate(-50%, -100%); font-size: 11px;
    font-weight: 700; color: var(--text); background: var(--surface-2); padding: 0 4px; border-radius: 3px;
    white-space: nowrap; }
.freact { position: absolute; bottom: 15px; height: 0; border-top: 2px dashed var(--c); cursor: help; }
.freact.never { border-top-color: var(--bad); opacity: 0.8; }
.focus-tl .tl-lab.f-cd, .focus-tl .tl-row.f-cd { height: 28px; }
.focus-tl .tl-lab.f-cd { gap: 6px; font-size: 12px; color: var(--text); cursor: help; }
.focus-tl .tl-lab.f-cd .ability-icon { width: 18px; height: 18px; border-radius: 4px; }
.focus-tl .tl-row.f-cd { border-bottom: 1px solid rgba(255,255,255,0.04); }
.focus-tl .tl-row.f-cd .m.cd { width: 20px; height: 20px; z-index: 2; }
.fbuff { position: absolute; top: 6px; bottom: 6px; border-radius: 4px; cursor: help; }
.fbuff.mine { background: color-mix(in srgb, var(--accent) 38%, transparent); box-shadow: inset 0 0 0 1px var(--accent); }
.fbuff.ext { background: rgba(201,133,0,0.38); box-shadow: inset 0 0 0 1px #e0a020; }
.fbuff:hover { filter: brightness(1.3); }
.focus-tl .tl-lab.f-cds, .focus-tl .tl-row.f-cds { height: 48px; }
.focus-tl .tl-row.f-cds .fpot { top: auto; bottom: 6px; height: 18px; }
.focus-tl .tl-row.f-cds .m.cd { top: auto; bottom: 7px; }
.focus-tl .tl-row.f-cds .m.cd { transform: translateX(-50%); }
.focus-tl .tl-lab.f-cds { color: var(--text); font-weight: 600; }
.fpot { position: absolute; top: 5px; bottom: 5px; border-radius: 4px; background: rgba(81,207,102,0.22);
    box-shadow: inset 0 0 0 1px rgba(81,207,102,0.7); cursor: help; }
.fpot span { position: absolute; left: 2px; top: 50%; transform: translateY(-50%); font-size: 11px; }
.focus-table .group-head th { font-size: 11px; letter-spacing: 0.04em; text-transform: uppercase; color: var(--faint);
    border-bottom: 1px solid var(--border); }
.focus-table .col-pull, .focus-table .col-all { border-left: 1px solid var(--border); }
/* Focus loading: a WoW cast bar (gold, a spark at the edge; green when done, red when interrupted) */
.castbar-wrap { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 36px 0 30px; }
.castbar { display: flex; align-items: center; gap: 10px; width: min(460px, 100%); }
.cb-icon { width: 40px; height: 40px; border-radius: 4px; flex-shrink: 0;
    box-shadow: 0 0 0 1px #000, 0 0 0 2px #8a6d2b; animation: cb-glow 1.6s ease-in-out infinite; }
@keyframes cb-glow { 50% { box-shadow: 0 0 0 1px #000, 0 0 0 2px #e8b64c, 0 0 14px rgba(240,180,60,0.55); } }
.cb-bar { position: relative; flex: 1; height: 26px; border-radius: 3px; overflow: hidden; background: #17120a;
    border: 1px solid #000; box-shadow: 0 0 0 1px #8a6d2b, inset 0 0 8px rgba(0,0,0,0.85); }
.cb-fill { position: absolute; left: 0; top: 0; bottom: 0; width: 0;
    background: linear-gradient(180deg, #ffd96a, #f2a400 48%, #c27800); }
.cb-fill::after { content: ''; position: absolute; right: -7px; top: -6px; bottom: -6px; width: 14px;
    background: radial-gradient(closest-side, rgba(255,255,225,0.95), rgba(255,215,110,0)); }
.cb-name, .cb-time { position: absolute; top: 0; line-height: 26px; font-size: 12px; font-weight: 700; color: #fff;
    text-shadow: 0 1px 2px #000, 0 0 3px #000; white-space: nowrap; }
.cb-name { left: 10px; right: 52px; overflow: hidden; text-overflow: ellipsis; }
.cb-time { right: 8px; font-variant-numeric: tabular-nums; }
.cb-flavor { margin: 0; min-height: 18px; font-size: 13px; font-style: italic; color: var(--muted); text-align: center; }
.castbar-wrap.done .cb-fill { background: linear-gradient(180deg, #8dff8d, #2fbf3a 48%, #1b7d24); }
.castbar-wrap.done .cb-fill::after, .castbar-wrap.failed .cb-fill::after { display: none; }
.castbar-wrap.failed .cb-fill { width: 100% !important; background: linear-gradient(180deg, #ff7a7a, #c62828 48%, #7a1717); }
.castbar-wrap.failed .cb-icon { animation: none; filter: grayscale(0.7); }
.castbar-wrap.failed .cb-flavor { font-style: normal; color: var(--text); }
.cb-retry[hidden] { display: none; }
@media (prefers-reduced-motion: reduce) { .cb-icon { animation: none; } }
/* Focus: toggles, spawn bars, add cards (tabs, share bars, chips), the damage-by-target meter */
.focus-tl .tl-chips { margin: 0 0 10px; }
.focus-tl .tl-chip i { background: var(--c); }
.focus-tl .tl-lab.f-spawns, .focus-tl .tl-row.f-spawns { height: 30px; }
.focus-tl .tl-lab.f-spawns { justify-content: space-between; gap: 6px; color: var(--text); font-size: 12px; padding-left: 2px; }
.focus-tl .tl-lab.f-spawns small { color: var(--faint); flex-shrink: 0; }
.focus-tl .tl-lab.f-spawns .pill { font-size: 9px; padding: 1px 6px; flex-shrink: 0; }
.fspawn { position: absolute; top: 6px; bottom: 6px; min-width: 4px; border-radius: 4px; cursor: help; overflow: hidden;
    background: linear-gradient(90deg, var(--c), color-mix(in srgb, var(--c) 45%, transparent)); }
.fspawn.died { box-shadow: inset -4px 0 0 #fff; background: var(--c); }
.fspawn span { position: absolute; left: 5px; top: 50%; transform: translateY(-50%); font-size: 10px; font-weight: 700;
    color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.6); white-space: nowrap; }
.fspawn:hover { filter: brightness(1.25); }
.fcard { padding: 14px 16px; }
.fcard-head b { font-size: 15px; }
.fcards.compact { grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); }
.fcards.prio { grid-template-columns: repeat(auto-fill, minmax(min(100%, 440px), 1fr)); }
.fcard.compact { padding: 10px 12px; }
.fcard.compact .fcard-head b { font-size: 13px; }
.ftabs { display: flex; flex-wrap: wrap; gap: 4px; margin: 10px 0 12px; border-bottom: 1px solid var(--border); }
.ftabs button { background: none; border: 0; border-bottom: 2px solid transparent; color: var(--muted); padding: 6px 10px;
    font: inherit; font-size: 12px; font-weight: 600; cursor: pointer; margin-bottom: -1px; }
.ftabs button:hover { color: var(--text); }
.ftabs button[aria-selected=true] { color: var(--text); border-bottom-color: var(--c); }
.fpane[hidden] { display: none; }
.fstats { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; margin-bottom: 12px; }
.fstats > div { background: var(--surface-3); border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 2px; }
.fstats span { font-size: 11px; color: var(--faint); text-transform: uppercase; letter-spacing: 0.04em; }
.fstats b { font-size: 20px; }
.fstats small { font-size: 11px; color: var(--muted); }
.fshare { position: relative; height: 10px; border-radius: 5px; background: var(--surface-3); margin: 6px 0; }
.fshare b { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 5px; background: var(--c); }
.fshare i { position: absolute; top: -4px; bottom: -4px; width: 2px; margin-left: -1px; background: var(--text); }
.fsrows { display: grid; gap: 6px; }
.fsrow { display: grid; grid-template-columns: 84px minmax(80px, 1fr) 66px 86px; gap: 10px; align-items: center; font-size: 12px; }
.fsrow.head { font-size: 10px; color: var(--faint); text-transform: uppercase; letter-spacing: 0.04em; }
.fs-when { font-weight: 600; font-variant-numeric: tabular-nums; }
.fchip { display: inline-block; text-align: center; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 700;
    font-variant-numeric: tabular-nums; background: var(--surface-3); }
.fchip.good { background: color-mix(in srgb, var(--good) 22%, transparent); color: var(--good); }
.fchip.ok { background: color-mix(in srgb, var(--warn) 22%, transparent); color: var(--warn); }
.fchip.bad { background: color-mix(in srgb, var(--bad) 22%, transparent); color: var(--bad); }
.fchip.none { color: var(--faint); font-weight: 400; }
.fchip.pot { background: rgba(81,207,102,0.16); color: #8ce99a; }
.fmetric { margin: 10px 0; }
.fmetric > span { font-size: 11px; color: var(--faint); text-transform: uppercase; letter-spacing: 0.04em; }
.fmetric em { font-style: normal; font-size: 12px; color: var(--muted); }
.fdps { position: relative; height: 22px; margin: 6px 0 4px; }
.fdps b, .fdps i { position: absolute; left: 0; height: 9px; border-radius: 4px; }
.fdps b { top: 0; background: var(--c); }
.fdps i { bottom: 0; background: var(--faint); opacity: 0.6; }
.fcds { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.fcds .ability-icon { width: 24px; height: 24px; border-radius: 5px; cursor: help; }
.fpstrip { position: relative; height: 26px; margin: 14px 0 4px; border-radius: 6px; background: var(--surface-3); }
.fpstrip i { position: absolute; }
.fpstrip .fp-add { top: 4px; height: 8px; border-radius: 3px; background: var(--c); }
.fpstrip .fp-buff { bottom: 4px; height: 8px; border-radius: 3px; background: #51cf66; opacity: 0.8; }
.fpstrip .fp-press, .fpstrip .fp-appear { top: -4px; bottom: -4px; width: 2px; margin-left: -1px; }
.fpstrip .fp-press { background: #8ce99a; } .fpstrip .fp-appear { background: var(--text); }
.fp-legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 12px; color: var(--muted); }
.fp-legend i { display: inline-block; width: 12px; height: 6px; border-radius: 2px; margin-right: 5px; vertical-align: 1px; }
.fp-legend .fp-add { background: var(--c); } .fp-legend .fp-buff { background: #51cf66; }
.fp-legend b { color: var(--text); }
.fcompact-meta { display: flex; justify-content: space-between; gap: 8px; font-size: 11px; color: var(--muted); }
.fsqs { display: flex; flex-wrap: wrap; gap: 3px; margin-top: 8px; }
.fsq { width: 14px; height: 14px; border-radius: 3px; cursor: help; background: var(--faint); }
.fsq.good { background: var(--good); } .fsq.ok { background: var(--warn); } .fsq.bad { background: var(--bad); }
.dtable td { vertical-align: middle; }
.dtable tbody tr:hover td, .dtable tr:hover td { background: rgba(255,255,255,0.03); }
.dname { display: flex; align-items: center; gap: 8px; border-left: 3px solid var(--c); padding-left: 8px; font-weight: 600; }
.dname .boss-portrait { width: 26px; height: 26px; border-radius: 6px; }
.dbar { position: relative; height: 28px; min-width: 200px; border-radius: 6px; background: var(--surface-3); overflow: hidden;
    display: flex; justify-content: space-between; align-items: center; }
.dbar::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: var(--w);
    background: linear-gradient(90deg, var(--c), color-mix(in srgb, var(--c) 55%, transparent)); }
.dbar span, .dbar b { position: relative; padding: 0 9px; font-variant-numeric: tabular-nums; text-shadow: 0 1px 2px rgba(0,0,0,0.65); }
.dbar span { font-weight: 700; color: #fff; } .dbar b { font-size: 12px; }
/* Every metric cell: one line - a 6px track (on the row's middle, like the damage bar's) and its value */
.dmeter { display: flex; align-items: center; gap: 10px; min-width: 150px; }
.dtrack { position: relative; flex: 1; min-width: 60px; height: 6px; border-radius: 3px; background: var(--surface-3); }
.dtrack > i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 3px; background: var(--c); }
.dtrack .dtick { left: 0; top: -5px; bottom: -5px; width: 2px; margin-left: -1px; border-radius: 1px; background: var(--text); }
.dval { flex: 0 0 56px; text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
.dmeter.wide { min-width: 220px; }
.dmeter.wide .dval { flex-basis: 104px; text-align: left; }
.dval small { font-weight: 400; color: var(--muted); margin-left: 4px; }
.dmeter.dtop .dval { color: #ff8000; }
.dtable td:last-child { text-align: left; }
.ddelta { display: inline-block; min-width: 58px; text-align: center; padding: 3px 8px; border-radius: 999px; font-size: 12px;
    font-weight: 700; font-variant-numeric: tabular-nums; background: var(--surface-3); color: var(--muted); }
.ddelta.good { background: color-mix(in srgb, var(--good) 22%, transparent); color: var(--good); }
.ddelta.bad { background: color-mix(in srgb, var(--bad) 22%, transparent); color: var(--bad); }
.fsw { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; }
.flegend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 4px 0 8px; font-size: 12px; color: var(--muted); }
.fcards { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; margin: 10px 0 16px; }
.fcard { background: var(--surface-2); border: 1px solid var(--border); border-left: 3px solid var(--c); border-radius: 10px;
    padding: 10px 14px; }
.fcard.prio { border-color: color-mix(in srgb, var(--c) 45%, var(--border)); border-left-color: var(--c); }
.fcard-head { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 8px; }
.fcard-head .pill { margin-left: auto; }
.fcard ul { margin: 8px 0 0; padding-left: 18px; font-size: 13px; color: var(--muted); }
.fcard li { margin: 3px 0; }
.fcard li b { color: var(--text); }
.cons-tl.multi .m { opacity: 0.6; }
.cons-tl.multi .m:hover { opacity: 1; }
@media (max-width: 600px) { .cons-tl { --label-w: 96px; } }
/* Spell tooltip (PAGE_JS) */
.sp-tip { position: fixed; z-index: 1000; max-width: 330px; padding: 9px 11px; border-radius: 8px; pointer-events: none;
    background: #10142a; border: 1px solid var(--border-strong); box-shadow: 0 10px 28px rgba(0,0,0,0.5);
    font-size: 12px; line-height: 1.45; color: var(--text); }
.sp-head { display: flex; align-items: center; gap: 8px; margin-bottom: 2px; }
.sp-head img { width: 22px; height: 22px; border-radius: 4px; }
.sp-name { font-weight: 600; font-size: 13px; }
.sp-meta { color: var(--muted); font-size: 11px; }
.sp-ctx { margin-top: 4px; color: #ffd43b; }
.sp-desc { margin-top: 6px; color: #c9cfe6; white-space: pre-line; }
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
.boss-tab { display: flex; align-items: center; gap: 10px; padding: 8px 14px 8px 8px; border-radius: 12px;
    background: var(--surface-2); color: var(--text); border: 1px solid var(--border);
    transition: border-color .15s, background .15s, box-shadow .15s; }
.boss-tab:hover { border-color: var(--border-strong); text-decoration: none; }
.boss-tab.active { border-color: var(--accent); background: var(--accent-soft); box-shadow: 0 0 0 3px rgba(109,124,255,0.18); }
.boss-tab small { display: block; color: var(--muted); margin-top: 2px; }
.boss-portrait { width: 40px; height: 40px; border-radius: 10px; flex: none; object-fit: cover;
    box-shadow: 0 0 0 2px var(--surface-3); background: var(--surface-3); }
.boss-portrait.killed { box-shadow: 0 0 0 2px var(--good); }
.boss-portrait.sm { width: 26px; height: 26px; border-radius: 7px; vertical-align: middle; margin-right: 8px; }
.boss-portrait.lg { width: 52px; height: 52px; border-radius: 12px; vertical-align: middle; margin-right: 12px; }
.boss-tab:not(.active) .boss-portrait { filter: saturate(0.7); }
.chips-label { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase;
    color: var(--faint); margin-right: 4px; }
.pull-chips { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 12px; align-items: center; }
.pull-chip { padding: 4px 10px; border-radius: 8px; background: var(--surface-2); color: var(--text);
    font-size: 13px; font-variant-numeric: tabular-nums; border: 1px solid var(--border); cursor: pointer;
    font-family: inherit; }
.pull-chip:hover { border-color: var(--border-strong); text-decoration: none; }
.pull-chip.kill { color: var(--good); }
.pull-chip.overall { font-weight: 600; }
.pull-chip.active { border-color: var(--accent); background: var(--accent-soft); }
.view-tabs { display: flex; gap: 6px; margin-top: 18px; padding: 5px; border-radius: 14px;
    background: var(--bg); border: 1px solid var(--border); }
.view-tab { flex: 1; display: flex; align-items: center; gap: 12px; padding: 11px 16px; border-radius: 10px;
    color: var(--muted); border: 1px solid transparent; transition: background .15s, color .15s; }
.view-tab .vt-icon { font-size: 22px; line-height: 1; }
.view-tab strong { display: block; font-size: 15px; color: inherit; }
.view-tab small { display: block; font-size: 12px; color: var(--faint); margin-top: 1px; }
.view-tab:hover { color: var(--text); background: var(--surface-2); text-decoration: none; }
.view-tab.active { color: #fff; background: linear-gradient(135deg, var(--accent), #5a4fd0);
    border-color: rgba(255,255,255,0.12); box-shadow: 0 6px 18px rgba(109,124,255,0.28); }
.view-tab.active small { color: rgba(255,255,255,0.8); }

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

/* Overview filters */
.filter-bar { display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }
.filter-bar label { display: flex; gap: 8px; align-items: center; font-size: 13px; color: var(--muted); }
.filter-bar select { width: auto; margin: 0; padding: 8px 12px; font-size: 14px; }

/* Score breakdown */
.breakdown { display: grid; gap: 10px; margin-top: 10px; }
.comp-head { display: flex; justify-content: space-between; gap: 10px; font-size: 13px; }
.comp-head b { font-variant-numeric: tabular-nums; }
.comp .subscore-track { margin: 4px 0 3px; }
.comp-detail { font-size: 12px; color: var(--muted); }
.subscore-fill.neutral { background: var(--faint); }
.subscore-track.marked { position: relative; }
.subscore-mark { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: var(--text);
                 opacity: 0.75; }
details.breakdown-toggle > summary { cursor: pointer; font-size: 13px; color: #9aa6ff; list-style: none; }
details.breakdown-toggle > summary::before { content: '▸ '; }
details.breakdown-toggle[open] > summary::before { content: '▾ '; }

/* Clips */
.clip-btn { display: inline-flex; align-items: center; gap: 4px; margin-left: 8px; padding: 2px 8px 2px 6px;
    font: inherit; font-size: 11px; font-weight: 600; line-height: 16px; border-radius: 999px; cursor: pointer;
    vertical-align: middle; color: #b9c2ff; background: var(--accent-soft); border: 1px solid rgba(109,124,255,0.45); }
.clip-btn svg { width: 13px; height: 13px; flex: none; }
.clip-btn:hover { color: #fff; background: var(--accent); border-color: var(--accent); }
.clip-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--faint); }
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
    .view-tab { padding: 9px 10px; gap: 8px; }
    .view-tab small { display: none; }
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
  const rows = [...table.querySelectorAll('tr')].filter(r => r.querySelector('td') && !r.classList.contains('mech-detail'));
  const details = new Map(rows.map(r => [r, r.nextElementSibling && r.nextElementSibling.classList.contains('mech-detail')
                                              ? r.nextElementSibling : null]));
  const asc = th.dataset.dir !== 'asc'; th.dataset.dir = asc ? 'asc' : 'desc';
  const val = r => { const c = r.children[idx]; const v = c.dataset.v ?? c.textContent.trim();
                     return isNaN(+v) || v === '' ? v.toLowerCase() : +v; };
  rows.sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * (asc ? 1 : -1));
  rows.forEach(r => { r.parentNode.appendChild(r); if (details.get(r)) r.parentNode.appendChild(details.get(r)); });
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
// Mechanics table: tag chips filter the rows; clicking a row (not its tag buttons / links) expands it.
document.querySelectorAll('.mech-wrap').forEach(wrap => {
  const apply = () => {
    const on = new Set([...wrap.querySelectorAll('.tl-chip[data-mg][aria-pressed=true]')].map(c => c.dataset.mg));
    let shown = 0;
    wrap.querySelectorAll('tr.mech-row').forEach(row => {
      row.hidden = !on.has(row.dataset.mg);
      shown += row.hidden ? 0 : 1;
      const detail = row.nextElementSibling;
      if (detail && detail.classList.contains('mech-detail')) detail.hidden = row.hidden || !row.classList.contains('open');
    });
    wrap.querySelector('.mech-empty').hidden = shown > 0;
  };
  wrap.querySelectorAll('.tl-chip[data-mg]').forEach(chip => chip.addEventListener('click', () => {
    chip.setAttribute('aria-pressed', chip.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
    apply();
  }));
  const toggle = row => {
    row.classList.toggle('open');
    const detail = row.nextElementSibling;
    if (detail && detail.classList.contains('mech-detail')) detail.hidden = !row.classList.contains('open');
  };
  wrap.querySelectorAll('tr.mech-row').forEach(row => {
    row.addEventListener('click', e => { if (!e.target.closest('a, button, form, input')) toggle(row); });
    row.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target === row) toggle(row); });
  });
  apply();
});
// Consumables timeline: the chips and the Abilities checkboxes choose what's drawn.
document.querySelectorAll('.cons-tl').forEach(tl => {
  const boxes = [...tl.querySelectorAll('.tl-pick input')];
  const marks = [...tl.querySelectorAll('.tl-inner [data-f]')];
  const apply = () => {
    const on = new Set([...tl.querySelectorAll('.tl-chip[data-f][aria-pressed=true]')].map(b => b.dataset.f));
    const picked = new Set(boxes.filter(b => b.checked).map(b => b.value));
    marks.forEach(el => { el.hidden = !(el.dataset.f === 'cd' ? picked.has(el.dataset.ab) : on.has(el.dataset.f)); });
    tl.querySelectorAll('.tl-chip[data-cat]').forEach(chip => {
      const mine = boxes.filter(b => b.dataset.cat === chip.dataset.cat), n = mine.filter(b => b.checked).length;
      chip.setAttribute('aria-pressed', n && n === mine.length ? 'true' : 'false');
      chip.classList.toggle('partial', n > 0 && n < mine.length);
    });
  };
  tl.querySelectorAll('.tl-chip').forEach(chip => chip.addEventListener('click', () => {
    if (chip.dataset.cat) {
      const mine = boxes.filter(b => b.dataset.cat === chip.dataset.cat), all = mine.every(b => b.checked);
      mine.forEach(b => { b.checked = !all; });
    } else {
      chip.setAttribute('aria-pressed', chip.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
    }
    apply();
  }));
  boxes.forEach(b => b.addEventListener('change', apply));
  apply();
});
// Focus loading: a cast bar while ?focus_load=1 fetches the pull from Warcraft Logs, then a reload
// (the browser keeps the scroll position) renders the timeline from the stored data.
document.querySelectorAll('[data-focus-load]').forEach(box => {
  const fill = box.querySelector('.cb-fill'), time = box.querySelector('.cb-time');
  const name = box.querySelector('.cb-name'), flavor = box.querySelector('.cb-flavor');
  const lines = JSON.parse(box.dataset.lines || '[]'), CAST = 8;  // a typical load, in seconds
  const t0 = performance.now();
  let finished = false, n = 0;
  const frame = () => {
    if (finished) return;
    const s = (performance.now() - t0) / 1000;  // full speed to 90 %, then ever slower: never "done" by itself
    const p = s < CAST ? 0.9 * s / CAST : 0.9 + 0.09 * (1 - Math.exp(-(s - CAST) / 8));
    fill.style.width = (100 * p).toFixed(1) + '%';
    time.textContent = s.toFixed(1);
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
  const rotate = setInterval(() => { if (lines.length) flavor.textContent = lines[++n % lines.length]; }, 2400);
  const fail = why => {
    finished = true; clearInterval(rotate);
    box.classList.add('failed'); name.textContent = 'Interrupted'; time.textContent = '';
    flavor.textContent = why || "Warcraft Logs didn't answer - try again in a bit.";
    const retry = box.querySelector('.cb-retry');
    retry.hidden = false; retry.onclick = () => location.reload();
  };
  const url = new URL(location.href);
  url.hash = '';
  url.searchParams.set('focus_load', '1');
  fetch(url, {credentials: 'same-origin', headers: {Accept: 'application/json'}})
    .then(r => r.ok ? r.json() : Promise.reject())
    .then(res => {
      if (!res.ok) return fail(res.why);
      finished = true; clearInterval(rotate);
      box.classList.add('done'); fill.style.width = '100%'; name.textContent = 'Cast complete';
      flavor.textContent = 'Here it comes…';
      setTimeout(() => location.reload(), 400);
    })
    .catch(() => fail());
});
// Focus cards: Overall / per-spawn tabs.
document.querySelectorAll('.fcard .ftabs').forEach(bar => bar.querySelectorAll('[data-tab]').forEach(btn => {
  btn.addEventListener('click', () => {
    const card = bar.closest('.fcard');
    bar.querySelectorAll('[data-tab]').forEach(b => b.setAttribute('aria-selected', b === btn ? 'true' : 'false'));
    card.querySelectorAll('.fpane').forEach(p => { p.hidden = p.dataset.pane !== btn.dataset.tab; });
  });
}));
// Focus timeline: your cooldowns / buffs from others - a chip per group, the picker per ability; a group's
// header hides with its last ability.
document.querySelectorAll('.focus-tl').forEach(tl => {
  const boxes = [...tl.querySelectorAll('.tl-pick input')];
  const lanes = key => tl.querySelectorAll('.tl-labels [data-g="' + key + '"], .tl-inner [data-g="' + key + '"]');
  const apply = () => {
    boxes.forEach(b => lanes(b.value).forEach(el => { el.hidden = !b.checked; }));
    tl.querySelectorAll('.tl-chip[data-cat]').forEach(chip => {
      const mine = boxes.filter(b => b.dataset.cat === chip.dataset.cat), n = mine.filter(b => b.checked).length;
      chip.setAttribute('aria-pressed', n ? 'true' : 'false');
      chip.classList.toggle('partial', n > 0 && n < mine.length);
      lanes(chip.dataset.cat).forEach(el => { el.hidden = !n; });
    });
  };
  tl.querySelectorAll('.tl-chip[data-cat]').forEach(chip => chip.addEventListener('click', () => {
    const mine = boxes.filter(b => b.dataset.cat === chip.dataset.cat), all = mine.every(b => b.checked);
    mine.forEach(b => { b.checked = !all; });
    apply();
  }));
  boxes.forEach(b => b.addEventListener('change', apply));
});
// Compare and Focus timelines: chips show/hide a group of lanes; Align phases / Real time swaps positions.
document.querySelectorAll('.cmp-tl, .focus-tl').forEach(tl => {
  tl.querySelectorAll('.tl-chip[data-g]').forEach(chip => chip.addEventListener('click', () => {
    const on = chip.getAttribute('aria-pressed') !== 'true';
    chip.setAttribute('aria-pressed', on ? 'true' : 'false');
    tl.querySelectorAll('.tl-labels [data-g="' + chip.dataset.g + '"], .tl-inner [data-g="' + chip.dataset.g + '"]')
      .forEach(el => { el.hidden = !on; });
  }));
  tl.querySelectorAll('[data-mode]').forEach(btn => btn.addEventListener('click', () => {
    const real = btn.dataset.mode === 'real';
    tl.classList.toggle('real', real);
    tl.querySelectorAll('[data-mode]').forEach(b => b.setAttribute('aria-pressed', b === btn ? 'true' : 'false'));
    tl.querySelectorAll('.m[data-a]').forEach(m => { m.style.left = real ? m.dataset.r : m.dataset.a; });
  }));
});
// Editor-style timelines: drag to pan, Ctrl/Cmd/Alt + scroll (or pinch) zooms around the pointer, the
// slider and -/+/Fit zoom around the middle, a playhead shows the time under the mouse.
document.querySelectorAll('.tl').forEach(tl => {
  const duration = +tl.dataset.duration, scroll = tl.querySelector('.tl-scroll'), inner = tl.querySelector('.tl-inner');
  const grid = tl.querySelector('.tl-grid'), ruler = tl.querySelector('.tl-ruler'), head = tl.querySelector('.tl-head');
  const slider = tl.querySelector('input[type=range]'), track = tl.querySelector('.tl-track');
  const maxZoom = Math.max(1, duration / 8000);  // all the way in = about 8 seconds across
  let zoom = 1;
  slider.disabled = maxZoom === 1;
  const clock = (ms, digits) => {
    const s = ms / 1000, rest = digits ? (s % 60).toFixed(digits) : String(Math.round(s % 60) % 60);
    return Math.floor((digits ? s : Math.round(s)) / 60) + ':' + rest.padStart(digits ? digits + 3 : 2, '0');
  };
  const drawAxis = () => {
    const width = inner.clientWidth, perMs = width / duration;
    const step = [1, 2, 5, 10, 15, 30, 60, 120, 300].map(s => s * 1000).find(s => s * perMs >= 64) || 600000;
    grid.replaceChildren(); ruler.replaceChildren();
    for (let t = 0; t <= duration; t += step) {
      if (track) {  // SVG track drawn in milliseconds (deaths strip)
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        const attrs = {class: 'grid', x1: t, x2: t, y1: 0, y2: track.viewBox.baseVal.height};
        Object.entries(attrs).forEach(([k, v]) => line.setAttribute(k, v));
        grid.appendChild(line);
      } else {      // HTML track, marks placed in %
        const line = document.createElement('i'); line.style.left = (100 * t / duration) + '%'; grid.appendChild(line);
      }
      if (t && t * perMs > width - 18) continue;
      const label = document.createElement('span');
      label.textContent = clock(t); label.style.left = (100 * t / duration) + '%';
      if (!t) label.className = 'first';
      ruler.appendChild(label);
    }
  };
  const setZoom = (z, anchor) => {  // anchor: px from the left edge of the visible track that stays put
    z = Math.min(maxZoom, Math.max(1, z));
    const x = anchor ?? scroll.clientWidth / 2, t = (scroll.scrollLeft + x) / inner.clientWidth * duration;
    zoom = z; inner.style.width = (100 * z) + '%';
    scroll.scrollLeft = t / duration * inner.clientWidth - x;
    if (maxZoom > 1) slider.value = Math.round(100 * Math.log(z) / Math.log(maxZoom));
    drawAxis();
  };
  scroll.addEventListener('wheel', e => {
    if (!(e.ctrlKey || e.metaKey || e.altKey)) return;
    e.preventDefault();
    setZoom(zoom * Math.exp(-e.deltaY * 0.0025), e.clientX - scroll.getBoundingClientRect().left);
  }, {passive: false});
  slider.addEventListener('input', () => setZoom(Math.pow(maxZoom, slider.value / 100)));
  tl.querySelectorAll('[data-zoom]').forEach(b => b.addEventListener('click', () =>
    setZoom(b.dataset.zoom === 'fit' ? 1 : zoom * (b.dataset.zoom === 'in' ? 2 : 0.5))));
  // Drag to pan (mouse / pen; touch scrolls natively). A drag never counts as a click on a row link.
  let drag = null, swallowClick = false;
  scroll.addEventListener('click', e => {
    if (swallowClick) { e.preventDefault(); e.stopPropagation(); swallowClick = false; }
  }, true);
  scroll.addEventListener('pointerdown', e => {
    swallowClick = false;
    if (e.pointerType === 'touch' || e.button !== 0) return;
    drag = {x: e.clientX, left: scroll.scrollLeft, moved: false, id: e.pointerId};
  });
  scroll.addEventListener('pointermove', e => {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    if (!drag.moved && Math.abs(dx) > 4) {
      drag.moved = true; scroll.setPointerCapture(drag.id); tl.classList.add('dragging');
    }
    if (drag.moved) scroll.scrollLeft = drag.left - dx;
  });
  const endDrag = () => {
    if (drag && drag.moved) { tl.classList.remove('dragging'); swallowClick = true; }
    drag = null;
  };
  scroll.addEventListener('pointerup', endDrag);
  scroll.addEventListener('pointercancel', endDrag);
  inner.addEventListener('pointermove', e => {
    const box = inner.getBoundingClientRect(), x = e.clientX - box.left;
    head.hidden = false; head.style.left = x + 'px';
    head.firstChild.textContent = clock(Math.max(0, x / box.width * duration), zoom > 4 ? 1 : 0);
  });
  inner.addEventListener('pointerleave', () => { head.hidden = true; });
  new ResizeObserver(drawAxis).observe(scroll);
});
// Rich tooltips for timeline marks: what/when from data-tip, plus the spell's name, icon, cooldown and
// Wowhead description from the timeline's spell-data JSON.
(() => {
  const tip = document.createElement('div');
  tip.className = 'sp-tip'; tip.hidden = true; document.body.appendChild(tip);
  const data = new WeakMap();
  const spellsFor = el => {
    const box = el.closest('.tl');
    if (!box) return {};
    if (!data.has(box)) {
      const node = box.querySelector('.spell-data');
      let parsed = {};
      try { parsed = node ? JSON.parse(node.textContent) : {}; } catch (e) { /* no spell text */ }
      data.set(box, parsed);
    }
    return data.get(box);
  };
  const line = (cls, text, parent) => {
    const div = document.createElement('div'); div.className = cls; div.textContent = text; (parent || tip).appendChild(div);
  };
  const place = (x, y) => {
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(8, Math.min(x + 14, innerWidth - w - 8)) + 'px';
    tip.style.top = (y + 18 + h > innerHeight ? Math.max(8, y - h - 12) : y + 18) + 'px';
  };
  const fetched = new Map();  // spell id -> data, or a promise while it loads
  const remote = id => {
    if (!fetched.has(id)) {
      fetched.set(id, fetch('/raids/spell/' + id).then(r => r.ok ? r.json() : null).catch(() => null)
        .then(data => { fetched.set(id, data); return data; }));
    }
    return fetched.get(id);
  };
  let current = null;
  const show = (el, x, y) => {
    current = el;
    const id = el.dataset.spell;
    let spell = id ? spellsFor(el)[id] : null;
    if (id && (!spell || !spell.desc)) {
      const got = remote(id);
      if (got && !(got instanceof Promise)) spell = Object.assign({}, spell || {}, got);
      else if (got) got.then(() => { if (current === el && !tip.hidden) show(el, lastX, lastY); });
    }
    tip.replaceChildren();
    if (spell) {
      const headRow = document.createElement('div'); headRow.className = 'sp-head';
      if (spell.icon) { const img = document.createElement('img'); img.src = spell.icon; img.alt = ''; headRow.appendChild(img); }
      line('sp-name', spell.name, headRow);
      tip.appendChild(headRow);
      if (spell.meta) line('sp-meta', spell.meta);
    }
    if (el.dataset.tip) line('sp-ctx', el.dataset.tip);
    if (spell && spell.desc) line('sp-desc', spell.desc);
    else if (id && fetched.get(id) instanceof Promise) line('sp-meta', 'Loading description…');
    tip.hidden = !tip.childNodes.length;
    place(x, y);
  };
  let lastX = 0, lastY = 0;
  const target = e => e.target.closest && e.target.closest('.tl [data-tip], [data-spell]');
  document.addEventListener('pointerover', e => {
    const el = target(e);
    lastX = e.clientX; lastY = e.clientY;
    if (el && !el.closest('.dragging')) show(el, e.clientX, e.clientY); else { tip.hidden = true; current = null; }
  });
  document.addEventListener('pointermove', e => {
    lastX = e.clientX; lastY = e.clientY;
    if (!tip.hidden) place(e.clientX, e.clientY);
  });
  // Touch has no hover: a tap on an ability shows its tooltip (tap elsewhere hides it).
  document.addEventListener('pointerdown', e => {
    if (e.pointerType !== 'touch') return;
    const el = target(e);
    if (el) show(el, e.clientX, e.clientY); else tip.hidden = true;
  });
  document.addEventListener('scroll', () => { tip.hidden = true; }, true);
})();
// Mechanic clip pop-up: the Mythic Trap iframe only loads when someone opens it.
document.addEventListener('click', e => {
  const btn = e.target.closest('.clip-btn');
  const modal = document.getElementById('clip-modal');
  if (btn && !btn.dataset.embed.startsWith('https://www.mythictrap.com/')) return;  // only ever Mythic Trap
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

# A film strip: reads as "short clip" (and not as a YouTube logo, which a red ▶ did).
FILM_ICON = ('<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">'
             '<rect x="1.5" y="2.5" width="13" height="11" rx="2"/><path d="M4.5 2.5v11M11.5 2.5v11M1.5 6h3M1.5 10h3'
             'M11.5 6h3M11.5 10h3"/><path d="M7 6.3v3.4l2.6-1.7z" fill="currentColor" stroke="none"/></svg>')

CLIP_MODAL = """
<div id="clip-modal" class="clip-modal" hidden>
  <div class="clip-box" role="dialog" aria-modal="true">
    <div class="clip-eyebrow">🎞 Mechanic clip</div>
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


_ICON_FILE = __import__('re').compile(r'^[A-Za-z0-9_.-]{1,120}$')
_ICON_HOSTS = ('https://assets.rpglogs.com/', 'https://wow.zamimg.com/')


def safe_icon(icon):
    """
    An icon file name or URL we're willing to put in src="" / CSS url(): a plain file name, or a URL on
    the two icon hosts made of the same safe characters. Anything else (quotes, parentheses, ...) is
    dropped - icon names come from logs and Wowhead, and CSS url() isn't covered by HTML escaping.
    """
    if not icon:
        return None
    if icon.startswith(_ICON_HOSTS):
        host = next(h for h in _ICON_HOSTS if icon.startswith(h))
        rest = icon[len(host):]
        return icon if rest and all(_ICON_FILE.match(part) for part in rest.split('/')) else None
    return icon if _ICON_FILE.match(icon) else None


def json_for_script(data):
    """JSON safe inside <script type="application/json">: no '<' at all (no </script>, no <!--)."""
    import json
    return json.dumps(data, ensure_ascii=False).replace('<', BACKSLASH + 'u003c')


BACKSLASH = chr(92)


def section_head(icon, title, sub='', action=''):
    """
    A card's header: icon tile, title, optional one-paragraph explanation and an action on the right,
    with a divider under it. title / sub / action are HTML (escape what comes from data).
    """
    sub_html = f'<p class="sec-sub">{sub}</p>' if sub else ''
    action_html = f'<div class="sec-action">{action}</div>' if action else ''
    return (f'<div class="sec-head"><div class="sec-title"><span class="sec-icon">{icon}</span>'
            f'<div><h2>{title}</h2>{sub_html}</div></div>{action_html}</div>')


def subsection(title, body, extra_class=''):
    """A part of a card: divider + small label, so stacked parts don't run into each other."""
    return f'<section class="sub {extra_class}"><h3 class="sub-title">{title}</h3>{body}</section>'


def stat_tiles(tiles):
    """A row of key numbers: [(value_html, label)]."""
    items = ''.join(f'<div class="stat-tile"><b>{value}</b><span>{label}</span></div>' for value, label in tiles)
    return f'<div class="stat-tiles">{items}</div>'


def boss_portrait(encounter_id, size='', killed=False):
    """The boss's portrait from Warcraft Logs (56 px); size '' (tabs), 'sm' (tables) or 'lg' (titles)."""
    classes = ' '.join(c for c in ('boss-portrait', size, 'killed' if killed else '') if c)
    return (f'<img class="{classes}" src="https://assets.rpglogs.com/img/warcraft/bosses/{int(encounter_id)}-icon.jpg" '
            f'alt="" loading="lazy" onerror="this.style.visibility=\'hidden\'">')


def ability(name, icon=None, ability_id=None, guide=None):
    """Icon + name; hovering (or tapping) shows the spell's Wowhead tooltip (PAGE_JS), clicking opens Wowhead."""
    icon = safe_icon(icon)
    img = f'<img class="ability-icon" src="{ICON_BASE}{esc(icon)}" alt="" loading="lazy">' if icon else ''
    label = esc(name)
    spell = ''
    if ability_id and ability_id > 1:
        label = (f'<a href="https://www.wowhead.com/spell={int(ability_id)}" target="_blank" rel="noopener" '
                 f'style="color:inherit">{label}</a>')
        spell = f' data-spell="{int(ability_id)}"'
        from ..spells import offer
        offer([ability_id])  # its tooltip may be looked up on demand (/raids/spell)
    return f'<span class="ability-cell"{spell}>{img}{label}{guide_button(guide, name)}</span>'


def guide_button(guide, name=''):
    """
    A "🎞 Clip" chip that opens the Mythic Trap clip in a pop-up player right on the page (not a
    link away); abilities without a clip get their tip as a hover ℹ️.
    """
    if not guide:
        return ''
    tip = guide.get('tip') or guide.get('description') or ''
    if guide.get('video_url'):
        return (f' <button type="button" class="clip-btn" data-embed="{esc(guide["embed_url"])}" '
                f'data-title="{esc(guide["name"] or name)}" data-tip="{esc(tip)}" '
                f'title="Watch a short clip of how {esc(guide["name"] or name)} works - plays right here">'
                f'{FILM_ICON}Clip</button>')
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
        color = '#ff6b6b' if death.get('early') else 'rgba(255,255,255,0.3)'
        parts.append(f'<line x1="{x(death["t"]):.1f}" x2="{x(death["t"]):.1f}" y1="34" y2="52" '
                     f'stroke="{color}" stroke-width="2"><title>{fmt_duration(death["t"])} '
                     f'{esc(death["name"])} died to {esc(death["ability"])}</title></line>'
                     f'<line x1="{x(death["t"]):.1f}" x2="{x(death["t"]):.1f}" y1="30" y2="56" '
                     f'stroke="transparent" stroke-width="8"><title>{fmt_duration(death["t"])} '
                     f'{esc(death["name"])} died to {esc(death["ability"])}</title></line>')
    end_label = f'<text x="{width - right}" y="68" text-anchor="end">{fmt_duration(duration)}</text>'
    if analysis.get('wipe_at') is not None:
        wx = x(analysis['wipe_at'])
        wipe_text = f'half the raid dead {fmt_duration(analysis["wipe_at"])}'
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
            '<th data-sort class="num" title="Early deaths by mistake: one of the first 4 deaths of a pull, not part of a mass death">Early deaths</th>'
            '<th data-sort class="num" title="First player to die in a pull">First death</th>'
            '<th data-sort class="num" title="Share of pull time alive (until half the raid was dead)">Alive %</th>')
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
    """What's killing the raid: early deaths by mistake (who) plus deaths in mass deaths."""
    if not rows:
        return '<p class="muted">No early deaths by mistake or mass deaths. 🎉</p>'
    body = []
    for k in rows[:limit]:
        who = ", ".join(f"{esc(n)}" + (f" ×{c}" if c > 1 else "")
                        for n, c in sorted(k["players"].items(), key=lambda kv: -kv[1]))
        split = ' · '.join(part for part in (
            f'{k["mistakes"]} mistake{"s" if k["mistakes"] != 1 else ""}' if k.get('mistakes') else '',
            f'{k["mass"]} in mass deaths' if k.get('mass') else '') if part)
        body.append(f'<tr><td>{ability(k["name"], k["icon"], k["id"], guide_for(k["id"], k["name"]))}</td>'
                    f'<td class="num">{k["count"]}</td><td class="small">{split}</td>'
                    f'<td class="small">{who}</td></tr>')
    return (f'<div class="table-wrapper"><table class="compact"><tr><th>Killed by</th><th class="num">Deaths</th>'
            f'<th></th><th>Early deaths by mistake</th></tr>{"".join(body)}</table></div>')


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

def spell_data_json(spells, spell_lookup=None):
    """
    The tooltips' spell data: {id: {name, icon, meta, desc}} - Wowhead's text where we have it, the
    log's name and icon otherwise. spells: {id: (name, rpglogs icon file)}; spell_lookup(ids) ->
    {id: {'name', 'icon', 'meta', 'description'}} (spells.lookup).
    """
    from ..spells import icon_url, offer
    known = spell_lookup(list(spells)) if spell_lookup and spells else {}
    offer(spells)
    out = {}
    for sid, (name, icon) in spells.items():
        info = known.get(sid) or {}
        icon = safe_icon(icon)
        out[sid] = {'name': info.get('name') or name,
                    'icon': (icon if icon.startswith('http') else f'{ICON_BASE}{icon}') if icon
                            else safe_icon(icon_url(info.get('icon'))),
                    'meta': info.get('meta') or '', 'desc': info.get('description') or ''}
    return json_for_script(out)


def deaths_strip(rows, spell_lookup=None):
    """
    Every pull of a boss on one time axis, as an editor-style timeline: a bar per pull (its length),
    phase changes, death ticks (red = early death by mistake, grey = the rest) and where half the raid
    was dead. Pull names stay pinned on the left; the track zooms (Ctrl/⌘ + scroll or pinch around the
    pointer, slider, −/+/Fit) and scrolls sideways - see PAGE_JS. The track is drawn in milliseconds
    with preserveAspectRatio="none", so zooming is just a wider element and strokes stay crisp.
    rows: [{'label', 'href', 'duration', 'phases': [ms], 'deaths': [...], 'wipe_at', 'kill'}]
    """
    if not rows:
        return ''
    row_h = 22
    longest = max(r['duration'] for r in rows) or 1
    height = row_h * len(rows)
    labels = ''.join(f'<a href="{esc(r["href"])}" style="height:{row_h}px">{esc(r["label"])}</a>' for r in rows)
    grid = ''.join(f'<line class="grid" x1="{t}" x2="{t}" y1="0" y2="{height}"/>'
                   for t in range(0, longest + 1, 60000))
    ruler = ''.join(f'<span{" class=first" if not t else ""} style="left:{100 * t / longest:.3f}%">'
                    f'{fmt_duration(t)}</span>' for t in range(0, longest + 1, 60000))
    track, spells = [], {}
    for i, r in enumerate(rows):
        y = i * row_h
        parts = [f'<rect class="tl-hit" x="0" y="{y}" width="{longest}" height="{row_h}"/>',
                 f'<rect x="0" y="{y + 4}" width="{r["duration"]}" height="{row_h - 8}" '
                 f'fill="{"rgba(81,207,102,0.25)" if r["kill"] else "rgba(255,255,255,0.08)"}"/>']
        for start in r['phases']:
            parts.append(f'<line x1="{start}" x2="{start}" y1="{y + 3}" y2="{y + row_h - 3}" '
                         f'stroke="rgba(255,255,255,0.35)" stroke-width="1"/>')
        if r.get('wipe_at') is not None:
            parts.append(f'<g class="tl-mark" data-tip="Half the raid dead at {fmt_duration(r["wipe_at"])}">'
                         f'<line x1="{r["wipe_at"]}" x2="{r["wipe_at"]}" y1="{y + 2}" y2="{y + row_h - 2}" '
                         f'stroke="#ffd43b" stroke-width="2" stroke-dasharray="3 2"/>'
                         f'<line class="tl-hit-line" x1="{r["wipe_at"]}" x2="{r["wipe_at"]}" y1="{y}" y2="{y + row_h}"/></g>')
        for d in r['deaths']:
            color = '#ff6b6b' if d.get('early') else 'rgba(255,255,255,0.35)'
            if d.get('ability_id'):
                spells.setdefault(d['ability_id'], (d['ability'], d.get('icon')))
            from ..analyzer import death_note
            tip = f'{d["name"]} died at {fmt_duration(d["t"])} · {death_note(d)}'
            parts.append(f'<g class="tl-mark" data-tip="{esc(tip)}" data-spell="{d.get("ability_id") or ""}">'
                         f'<line x1="{d["t"]}" x2="{d["t"]}" y1="{y + 4}" y2="{y + row_h - 4}" stroke="{color}" '
                         f'stroke-width="3"/><line class="tl-hit-line" x1="{d["t"]}" x2="{d["t"]}" y1="{y}" '
                         f'y2="{y + row_h}"/></g>')
        track.append(f'<a href="{esc(r["href"])}">{"".join(parts)}</a>')
    return f"""<div class="tl" data-duration="{longest}">
        <div class="tl-tools"><span class="muted small">Drag to pan · Ctrl + scroll or pinch to zoom · hover for details</span>
            <button type="button" data-zoom="out" title="Zoom out">−</button>
            <input type="range" min="0" max="100" value="0" aria-label="Zoom">
            <button type="button" data-zoom="in" title="Zoom in">+</button>
            <button type="button" data-zoom="fit" title="Show the whole pull">Fit</button></div>
        <div class="tl-body">
            <div class="tl-labels">{labels}<div class="tl-ruler-gap"></div></div>
            <div class="tl-scroll"><div class="tl-inner">
                <svg class="tl-track" viewBox="0 0 {longest} {height}" preserveAspectRatio="none"
                     style="height:{height}px" role="img" aria-label="Deaths in every pull">
                    <g class="tl-grid">{grid}</g>{"".join(track)}</svg>
                <div class="tl-ruler">{ruler}</div>
                <div class="tl-head" hidden><span></span></div>
            </div></div>
        </div>
        <script type="application/json" class="spell-data">{spell_data_json(spells, spell_lookup)}</script>
        </div>"""


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


def pull_histogram(bins, our_pulls=None, killed=False):
    """
    How many pulls the guilds that killed a boss needed (single series), with a labelled
    marker for where we are. bins: [(start, end, count)].
    """
    if not bins:
        return ''
    width, height, left, right, top, bottom = 900, 200, 36, 16, 26, 28
    lo, hi = bins[0][0], max(bins[-1][1], (our_pulls or 0) * 1.05)
    peak = max(c for _, _, c in bins) or 1
    inner_w, inner_h = width - left - right, height - top - bottom

    def x(v):
        return left + inner_w * (v - lo) / ((hi - lo) or 1)

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="Pulls needed by guilds that killed this boss">',
             f'<line class="grid" x1="{left}" x2="{width - right}" y1="{top + inner_h}" y2="{top + inner_h}"/>']
    for start, end, count in bins:
        h = inner_h * count / peak
        parts.append(f'<rect x="{x(start) + 1:.1f}" y="{top + inner_h - h:.1f}" width="{max(1, x(end) - x(start) - 2):.1f}" '
                     f'height="{max(h, 0.5):.1f}" rx="3" fill="{SERIES_PULL}"><title>{start:.0f}–{end:.0f} pulls: '
                     f'{count} guild{"s" if count != 1 else ""}</title></rect>')
    step = max(1, int((hi - lo) / 8 / 10) * 10) or 10
    tick = int(lo // step * step)
    while tick <= hi:
        if tick >= lo:
            parts.append(f'<text x="{x(tick):.1f}" y="{height - 8}" text-anchor="middle">{tick}</text>')
        tick += step
    if our_pulls:
        ox = x(our_pulls)
        label = f'You: {our_pulls} pull{"s" if our_pulls != 1 else ""}{" (kill)" if killed else " so far"}'
        anchor = 'end' if ox > width * 0.75 else 'start'
        parts.append(f'<line x1="{ox:.1f}" x2="{ox:.1f}" y1="{top - 6}" y2="{top + inner_h}" stroke="{SERIES_BEST}" '
                     f'stroke-width="2.5"/><text x="{ox + (-6 if anchor == "end" else 6):.1f}" y="{top - 10}" '
                     f'text-anchor="{anchor}" fill="var(--text)" font-weight="600">{esc(label)}</text>')
    parts.append('</svg>')
    return ''.join(parts)
