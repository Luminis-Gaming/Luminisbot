"""Banner assets and markup must remain safe and useful with missing/partial artwork."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raidanalysis.web import brand


class TestGuildBanner(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.mock_root = patch.object(brand, 'ASSET_ROOT', self.root)
        self.mock_root.start()
        self.addCleanup(self.mock_root.stop)
        self.addCleanup(self.folder.cleanup)

    def manifest(self, count=4, name='Boopsboops'):
        data = {'characters': [{'id': str(i), 'name': name, 'poses': [
            {'id': 'idle', 'file': f'{i}.webp', 'width': 300, 'height': 400}]} for i in range(count)],
            'wordmark': {'file': 'logo.webp', 'width': 900, 'height': 300}}
        (self.root / 'manifest.json').write_text(json.dumps(data), encoding='utf-8')
        for character in data['characters']:
            (self.root / character['poses'][0]['file']).touch()
        (self.root / 'logo.webp').touch()
        return data

    def test_absent_assets_do_not_break_pages(self):
        self.assertEqual(brand.markup(), '')
        self.assertIsNone(brand.asset_path('missing.webp'))

    def test_banner_waits_for_four_distinct_characters(self):
        self.manifest(count=3)
        self.assertEqual(brand.markup(), '')
        self.manifest(count=5)
        markup = brand.markup()
        self.assertEqual(markup.count('class="guild-banner-character"'), 4)
        self.assertIn('class="guild-banner-word"', markup)

    def test_character_names_cannot_close_manifest_script(self):
        self.manifest(name='</script><script>alert(1)</script>')
        markup = brand.markup()
        self.assertNotIn('</script><script>', markup)
        self.assertIn('\\u003c/script>', markup)

    def test_asset_route_serves_only_manifest_files(self):
        self.manifest()
        (self.root / 'unlisted.webp').touch()
        self.assertEqual(brand.asset_path('logo.webp'), (self.root / 'logo.webp').resolve())
        for filename in ('unlisted.webp', '../logo.webp', '..\\logo.webp', 'manifest.json', 'missing.webp'):
            self.assertIsNone(brand.asset_path(filename))

    def test_missing_asset_is_not_a_valid_path(self):
        self.manifest()
        (self.root / 'logo.webp').unlink()
        self.assertIsNone(brand.asset_path('logo.webp'))

    def test_wordmark_is_left_to_the_script(self):
        self.manifest()
        markup = brand.markup()
        outside = markup.split('<noscript>')[0] + markup.split('</noscript>')[-1]
        self.assertNotIn('src="/raids/art/logo.webp"', outside)  # no download of one that's replaced at once
        self.assertIn('<noscript><img class="guild-banner-word" src="/raids/art/logo.webp"', markup)

    def test_a_changed_manifest_is_read_again(self):
        import os
        self.manifest(count=4)
        self.assertEqual(len(brand.read_manifest()['characters']), 4)
        self.manifest(count=6)
        path = self.root / 'manifest.json'
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10 ** 9))
        self.assertEqual(len(brand.read_manifest()['characters']), 6)

    def test_preview_and_admin_can_choose_home_and_asset_base(self):
        self.manifest()
        markup = brand.markup('/admin/raids', '../assets/')
        self.assertIn('href="/admin/raids"', markup)
        self.assertIn('src="../assets/logo.webp"', markup)


if __name__ == '__main__':
    unittest.main()
