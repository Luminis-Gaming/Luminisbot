const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');

const script = execFileSync('python', ['-c', 'from raidanalysis.web.brand import JS; print(JS)'], {encoding: 'utf8'});
const fixture = {base: '/raids/art/', wordmarks: Array.from({length: 6}, (_, i) => ({
  file: `logo-${i}.webp`, width: 900, height: 300,
})), characters: Array.from({length: 36}, (_, i) => ({
  id: `character-${i}`, name: `Character ${i}`, poses: Array.from({length: 6}, (_, j) => ({
    id: `pose-${j}`, file: `character-${i}-pose-${j}.webp`, width: 500, height: 700,
  })),
}))};
const manifest = process.argv[2]
  ? {base: '/raids/art/', ...JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))}
  : fixture;
const poseOf = new Map(manifest.characters.flatMap(character => character.poses.map(pose => [
  manifest.base + pose.file, pose.id || pose.file.replace(/^.*-pose-/, '')])));
const storage = new Map();
function run({data = manifest, disabledStorage = false, random = Math.random} = {}) {
  let images = [];
  const word = {};
  const banner = {dataset: {}, querySelector(selector) {
    if (selector === '.guild-banner-word') return word;
    return selector === '[data-guild-cast]'
      ? {textContent: JSON.stringify(data)} : {replaceChildren: (...values) => { images = values; }};
  }};
  const sandbox = {
    document: {querySelector: () => banner, createElement: () => ({addEventListener() {}})},
    Math: Object.assign(Object.create(Math), {random}),
    sessionStorage: {
      getItem(key) { if (disabledStorage) throw Error('Disabled'); return storage.get(key); },
      setItem(key, value) { if (disabledStorage) throw Error('Disabled'); storage.set(key, value); },
    },
  };
  vm.runInNewContext(script, sandbox);
  return {images, wordmark: word.src, layout: banner.dataset.layout};
}
let previous = '';
const seen = new Set();
const seenPoses = new Set();
const seenWordmarks = new Set();
const seenLayouts = new Set();
let previousWordmark;
let previousLayout;
let seed = 17;
const seededRandom = () => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 4294967296);
for (let i = 0; i < 1000; i++) {
  const {images, wordmark, layout} = run({random: seededRandom});
  assert.notEqual(wordmark, previousWordmark);
  assert.notEqual(layout, previousLayout);
  previousWordmark = wordmark;
  previousLayout = layout;
  seenWordmarks.add(wordmark);
  seenLayouts.add(layout);
  assert.equal(images.length, 4);
  assert.equal(new Set(images.map(image => image.alt)).size, 4);
  assert.equal(new Set(images.map(image => poseOf.get(image.src))).size, 4, 'Four characters, four different poses.');
  const signature = images.map(image => image.alt).sort().join('|');
  assert.notEqual(signature, previous);
  previous = signature;
  images.forEach(image => { seen.add(image.alt); seenPoses.add(image.src); });
}
assert.equal(seen.size, manifest.characters.length);
assert.equal(seenPoses.size, manifest.characters.reduce((count, c) => count + c.poses.length, 0));
assert.equal(seenWordmarks.size, manifest.wordmarks.length);
assert.equal(seenLayouts.size, 3);
assert.equal(run({disabledStorage: true}).images.length, 4);
assert.equal(run({data: {characters: []}}).images.length, 0);
const first = run({random: () => 0}).images.map(image => image.alt).sort().join('|');
const second = run({random: () => 0}).images.map(image => image.alt).sort().join('|');
assert.notEqual(first, second, 'Even a repeated shuffle must replace at least one character.');
console.log(`Banner randomization: 1,000 reloads, ${seen.size} characters, ${seenPoses.size} poses, ${seenWordmarks.size} wordmarks, three layouts.`);
