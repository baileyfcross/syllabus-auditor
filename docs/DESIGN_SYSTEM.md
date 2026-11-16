# Syllabus Auditor design system

Copyright (c) 2026 Bailey Cross. Application source is licensed under MIT (see root `LICENSE`).

## Purpose and layering

The current HTML/CSS/JavaScript UI is used by FastAPI in the browser and by
pywebview in the desktop builds. There is **no React, Vite, Tailwind CDN, or
client-side CSS compilation**. Build-time Tailwind v4 is an **optional authoring
utility**, not a dependency of end-user installations.

CSS load order in `app/static/index.html`:

1. `tailwind.generated.css`: compiled, prefixed Tailwind utilities (may start as a placeholder).
2. `app.css`: existing application-specific styles and dark mode selectors.
3. `design-system.css`: authoritative semantic tokens and component standards.

The last sheet standardizes current screens while preserving the legacy CSS.
When editing a page, prefer migrating old hard-coded styles to the semantic
variables and reusable `.sa-*` components rather than adding another color.

## Token source of truth

**Edit `app/static/design-system.css`** to change colors, typography, spacing,
radius, control heights, focus rings, shadows, or light/dark palettes.
Keep `app/static/theme.js` as-is: it manages `light`, `dark`, and `system` via
`<html data-theme=...>`. Theme tokens are overridden under
`:root[data-theme="dark"]` and inherited by every component and Tailwind utility.

Examples:

| Purpose | CSS variable | Tailwind utility |
| --- | --- | --- |
| Page background | `--sa-bg-canvas` | `tw:bg-sa-canvas` |
| Panel background | `--sa-bg-surface` | `tw:bg-sa-surface` |
| Body text | `--sa-text` | `tw:text-sa-text` |
| Muted text | `--sa-text-muted` | `tw:text-sa-muted` |
| Border | `--sa-border` | `tw:border-sa-border` |
| Brand color | `--sa-primary` | `tw:bg-sa-primary` |
| Controls | `--sa-radius-md` | `tw:rounded-sa-md` |
| Panel radius | `--sa-radius-lg` | `tw:rounded-sa-lg` |

Tailwind custom token mappings are in `styles/tailwind.css`. All color values
come from the `--sa-*` variables. Use the `tw:` prefix for all Tailwind classes
(e.g. `tw:flex`, `tw:md:grid-cols-2`) so existing `.grid`, `.flex`, `.hidden`,
and other application classes remain stable. Do not construct dynamic Tailwind
class names in JavaScript: source detection only sees literal complete classes.

## Component standards

| Existing class | New component class | Use |
| --- | --- | --- |
| `.panel` | `.sa-card` | Reusable surfaces and borders |
| `.panel-pad` | `.sa-card-body` | Consistent interior padding |
| `.btn.primary` | `.sa-button.sa-button--primary` | Primary action |
| `.btn.small` | `.sa-button.sa-button--small` | Compact action |
| `.btn.ghost` | `.sa-button.sa-button--ghost` | Tertiary action |
| `.field` | `.sa-field` | Form row with labels and control |
| `.actions` | `.sa-inline` | Responsive inline action group |
| `.modal-title` | `.sa-toolbar` | Flex header/toolbar |
| `.pill` | `.sa-badge` | Status metadata |
| `.line` | `.sa-divider` | Quiet separator |

Existing components retain their class names. The shared JS helper functions
now include `.sa-button`, `.sa-field`, and `.sa-toolbar` in generated markup.
This keeps all existing UI selectors, event hooks, and behavior working.

### Examples

```html
<section class="sa-card tw:rounded-sa-lg">
  <div class="sa-card-header">
    <h2 class="sa-section-title">Institution policies</h2>
    <button class="sa-button sa-button--primary">Add policy</button>
  </div>
  <div class="sa-card-body tw:grid tw:gap-4 tw:md:grid-cols-2">
    <div class="sa-field">
      <label class="sa-label" for="policy-name">Policy name</label>
      <input class="sa-input" id="policy-name" />
    </div>
  </div>
</section>
```

## Development workflow

Requirements: Node.js 20+ and npm for **developers only**. Python remains the
application runtime and FastAPI serves static CSS normally.

```bash
npm install
npm run build:css
# For live regeneration during styling work:
npm run watch:css
```

Commit `package.json`, the npm-generated `package-lock.json`, and the **compiled**
`app/static/tailwind.generated.css` so GitHub checkouts and published installers
already have the CSS. Do **not** add `node_modules/` to version control.

The patch intentionally ships an initial CSS placeholder because the build
environment used to prepare this patch cannot access the npm registry. Run
`npm install && npm run build:css` once before publishing a release. This is
required to activate the Tailwind utility classes. The semantic CSS component
system works immediately, even before compilation.

No PyInstaller, Inno Setup, macOS PyInstaller, or Docker packaging changes are
needed: they already copy `app/static`, including both stylesheets.
Do not reference Tailwind via a hosted CDN; the strict CSP forbids it and
end-user builds should work offline.

## Design and accessibility rules

- One primary call to action per screen or context; secondary buttons are neutral.
- Use semantic color names, never arbitrary hard-coded colors in newly added views.
- Keep label and control pairings with accessible `for` / `id` attributes.
- Support keyboard focus (`:focus-visible`) and disabled states.
- Respect `prefers-reduced-motion`.
- Test light, dark and system themes at both narrow and wide viewport sizes.
- Make tables scroll inside `.table-scroll` rather than shrinking text.
- The audit document text and evidence formatting may require specialized CSS;
  don't replace those display rules with generic component utilities.

## Licensing note

The root MIT `LICENSE` contains the requested copyright notice. MIT permits
others to use, modify, redistribute, and commercially use this code while
retaining the license/copyright notice. Third-party libraries and Qwen model
weights retain their own licenses; this project license does not relicense them.
