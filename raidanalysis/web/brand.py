"""Guild wordmark and four distinct raiders, picked afresh by the browser on every load."""
import html
import json
from pathlib import Path

ASSET_ROOT = Path(__file__).parent / 'static' / 'cartoons'
ASSET_URL = '/raids/art/'

CSS = r"""
.guild-banner { position: relative; isolation: isolate; display: block; width: 100%;
    max-width: 1050px; aspect-ratio: 2.6; margin: 0 auto 22px; overflow: hidden;
    border-radius: 18px; background: radial-gradient(ellipse at 50% 85%, #262c46, transparent 70%); }
.guild-banner:hover { text-decoration: none; }
.guild-banner-cast { position: absolute; inset: 2% 3% 0; display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr)); align-items: start; z-index: 1; }
.guild-banner-character { width: 118%; height: 92%; max-height: 100%; margin-left: -9%;
    object-fit: contain; object-position: center top; filter: drop-shadow(0 2px 2px #0d1020); }
.guild-banner-word { position: absolute; z-index: 2; width: 72%; height: 52%;
    left: 14%; bottom: 1%; object-fit: contain; filter: drop-shadow(0 3px 1px #0d1020); }
.guild-banner-word:not([src]) { visibility: hidden; }
.guild-banner[data-layout="arc"] .guild-banner-character:nth-child(1),
.guild-banner[data-layout="arc"] .guild-banner-character:nth-child(4) { transform: translateY(6%); height: 86%; }
.guild-banner[data-layout="arc"] .guild-banner-character:nth-child(2),
.guild-banner[data-layout="arc"] .guild-banner-character:nth-child(3) { height: 98%; }
.guild-banner[data-layout="splayed"] .guild-banner-character:nth-child(1) { transform: rotate(-3deg); }
.guild-banner[data-layout="splayed"] .guild-banner-character:nth-child(2) { transform: rotate(2deg); }
.guild-banner[data-layout="splayed"] .guild-banner-character:nth-child(3) { transform: rotate(-2deg); }
.guild-banner[data-layout="splayed"] .guild-banner-character:nth-child(4) { transform: rotate(3deg); }
.guild-banner-word-fallback { position: absolute; bottom: 2%; width: 100%; z-index: 2;
    text-align: center; color: #ffce35; font: 900 clamp(40px, 9vw, 110px)/1 sans-serif; }
@media (max-width: 600px) {
    .guild-banner { aspect-ratio: 2.2; margin-bottom: 16px; }
    .guild-banner-cast { inset: 1% 0 0; }
    .guild-banner-character { width: 116%; margin-left: -8%; height: 88%; }
    .guild-banner-word { width: 76%; left: 12%; height: 48%; bottom: 1%; }
}
"""

JS = r"""
(() => {
  const banner = document.querySelector('[data-guild-banner]');
  if (!banner) return;
  let manifest;
  try { manifest = JSON.parse(banner.querySelector('[data-guild-cast]').textContent); }
  catch { return; }
  const freshChoice = (items, key) => {
    let index = Math.floor(Math.random() * items.length);
    try {
      if (items.length > 1 && String(index) === sessionStorage.getItem(key)) {
        index = (index + 1 + Math.floor(Math.random() * (items.length - 1))) % items.length;
      }
      sessionStorage.setItem(key, String(index));
    } catch {}
    return items[index];
  };
  const wordmarks = manifest.wordmarks || (manifest.wordmark ? [manifest.wordmark] : []);
  const word = banner.querySelector('.guild-banner-word');
  if (word && wordmarks.length) {
    const selected = freshChoice(wordmarks, 'luminis-banner-last-wordmark');
    word.src = manifest.base + selected.file;
    word.width = selected.width;
    word.height = selected.height;
  }
  banner.dataset.layout = freshChoice(['line', 'arc', 'splayed'], 'luminis-banner-last-layout');
  const characters = manifest.characters.filter(character => character.poses.length);
  if (characters.length < 4) return;
  const shuffle = items => {
    const out = items.slice();
    for (let i = out.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [out[i], out[j]] = [out[j], out[i]];
    }
    return out;
  };
  const shuffled = shuffle(characters);
  let cast = shuffled.slice(0, 4);
  const key = 'luminis-banner-last-cast';
  const signature = selected => selected.map(character => character.id).sort().join('|');
  try {
    const previous = sessionStorage.getItem(key);
    if (characters.length > 4 && signature(cast) === previous) cast[3] = shuffled[4];
    sessionStorage.setItem(key, signature(cast));
  } catch {} // Storage may be disabled; randomness still works.
  const container = banner.querySelector('.guild-banner-cast');
  // Four different poses too, while the characters have them: an idle line-up, a victory, a faceplant...
  const usedPoses = new Set();
  const images = cast.map(character => {
    const fresh = character.poses.filter(pose => !usedPoses.has(pose.id));
    const pool = fresh.length ? fresh : character.poses;
    const pose = pool[Math.floor(Math.random() * pool.length)];
    usedPoses.add(pose.id);
    const image = document.createElement('img');
    image.className = 'guild-banner-character';
    image.src = manifest.base + pose.file;
    image.alt = character.name;
    image.title = character.name;
    image.decoding = 'async';
    image.fetchPriority = 'high';  // the top of every page
    image.width = pose.width;
    image.height = pose.height;
    image.addEventListener('error', () => { image.hidden = true; }, {once: true});
    return image;
  });
  container.replaceChildren(...images);
})();
"""


_manifest_cache = {'key': None, 'manifest': None}


def read_manifest():
    """
    An incomplete asset set can be previewed as soon as four characters exist. Parsed once per version of the
    file (every page and every banner image asks), read again only when it changes.
    """
    path = ASSET_ROOT / 'manifest.json'
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _manifest_cache['key'] != key:
        try:
            manifest = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            manifest = None
        _manifest_cache.update(key=key, manifest=manifest)
    return _manifest_cache['manifest']


def markup(home='/raids', base=ASSET_URL):
    manifest = read_manifest()
    if not manifest:
        return ''
    characters = [character for character in manifest['characters'] if character['poses']]
    if len(characters) < 4:
        return ''
    payload = dict(manifest, base=base)
    # Script data must never contain an HTML closing tag, even in a character name.
    data = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c')
    cast = ''.join(
        f'<img class="guild-banner-character" src="{html.escape(base + character["poses"][0]["file"], quote=True)}" '
        f'alt="{html.escape(character["name"], quote=True)}" '
        f'width="{character["poses"][0]["width"]}" height="{character["poses"][0]["height"]}">'
        for character in characters[:4]
    )
    wordmark = manifest.get('wordmark')
    if wordmark:
        # No src: the script picks the lettering, so the page doesn't download v1 first and then another one
        size = f'width="{wordmark["width"]}" height="{wordmark["height"]}"'
        word = (f'<img class="guild-banner-word" alt="" {size} aria-hidden="true">'
                f'<noscript><img class="guild-banner-word" src="{html.escape(base + wordmark["file"], quote=True)}" '
                f'alt="" {size} aria-hidden="true"></noscript>')
    else:
        word = '<span class="guild-banner-word-fallback" aria-hidden="true">LUMINIS</span>'
    return (f'<a class="guild-banner" data-guild-banner href="{html.escape(home, quote=True)}" '
            f'aria-label="Luminis guild home"><div class="guild-banner-cast"></div>'
            f'<noscript><div class="guild-banner-cast">{cast}</div></noscript>{word}'
            f'<script type="application/json" data-guild-cast>{data}</script></a>')


def asset_path(filename):
    """Only generated manifest assets are public, never source renders or arbitrary files."""
    manifest = read_manifest()
    if not manifest:
        return None
    allowed = {pose['file'] for character in manifest['characters'] for pose in character['poses']}
    if manifest.get('wordmark'):
        allowed.add(manifest['wordmark']['file'])
    allowed.update(wordmark['file'] for wordmark in manifest.get('wordmarks', []))
    if filename not in allowed or Path(filename).name != filename or '/' in filename or '\\' in filename:
        return None
    target = (ASSET_ROOT / filename).resolve()
    return target if target.parent == ASSET_ROOT.resolve() and target.is_file() else None
