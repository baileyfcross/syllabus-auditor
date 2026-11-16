"""Fast, dependency-free source checks for the UI design system patch."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'

class DesignSystemTests(unittest.TestCase):
    def test_license(self):
        text = (ROOT / 'LICENSE').read_text(encoding='utf-8')
        self.assertIn('Copyright (c) 2026 Bailey Cross', text)
        self.assertIn('Permission is hereby granted, free of charge', text)
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', text)

    def test_style_order_and_no_cdn(self):
        html = (STATIC / 'index.html').read_text(encoding='utf-8')
        links = ['tailwind.generated.css', 'app.css', 'design-system.css']
        self.assertEqual(sorted(html.index(k) for k in links), [html.index(k) for k in links])
        self.assertNotIn('cdn.tailwindcss.com', html)

    def test_shared_theme_tokens_and_controls(self):
        css = (STATIC / 'design-system.css').read_text(encoding='utf-8')
        for token in ('--sa-bg-canvas', '--sa-bg-surface', '--sa-text', '--sa-primary',
                      '--sa-border', '--sa-radius-md', '--sa-shadow-panel'):
            self.assertGreaterEqual(css.count(token), 3, token)
        self.assertIn(':root[data-theme="dark"]', css)
        for component in ('.sa-button', '.sa-field', '.sa-card', '.sa-toolbar'):
            self.assertIn(component, css)
        self.assertIn('focus-visible', css)

    def test_prefixed_tailwind_no_reset(self):
        source = (ROOT / 'styles' / 'tailwind.css').read_text(encoding='utf-8')
        self.assertIn('prefix(tw)', source)
        self.assertNotIn('@import "tailwindcss/preflight.css"', source)
        self.assertIn('@source "../app/static/app.js"', source)
        self.assertIn('var(--sa-primary)', source)
        app = (STATIC / 'app.js').read_text(encoding='utf-8')
        self.assertIn('sa-button tw:inline-flex', app)
        self.assertIn('sa-field tw:flex', app)
        self.assertIn('sa-toolbar tw:flex', app)

    def test_app_css_not_discarded(self):
        old = (STATIC / 'app.css').read_text(encoding='utf-8')
        self.assertIn('.audit-detail', old)
        self.assertIn('.docviewer', old)
        self.assertIn('[data-theme="dark"]', old)

if __name__ == '__main__':
    unittest.main()
