# Maya Unified Documentation

Quartz 5 static site for [maya-unified](https://github.com/System-Nebula/maya-unified).

**Published:** https://system-nebula.github.io/maya-unified/

## Local development

Requires Node.js ≥ 22.

```bash
cd docs
npm install
npm run install-plugins   # Linux/macOS; on Windows see note below
npm run serve             # http://localhost:8080
```

Hot reload while editing content:

```bash
npm run watch
```

Production build (output in `public/`):

```bash
npm run build
```

### Windows note

If `npm run install-plugins` fails with symlink (`EPERM`) errors, plugins are usually already cloned under `.quartz/plugins/`. Regenerate the index and build:

```bash
npx tsx ./scripts/regenerate-index.ts
npx tsx ./quartz/bootstrap-cli.mjs build --serve
```

Enable **Developer Mode** in Windows Settings to allow symlinks, or use WSL for plugin installs.

## Content

Markdown lives in `content/` with Obsidian-style wikilinks (`[[Architecture/Overview]]`). Regenerate stub pages from the generator script:

```bash
node ./scripts/generate-content.mjs
```

## Theme

Dark mode only — Maya palette (ink-violet background, orchid/cyan accents) in `quartz.config.yaml` and `quartz/styles/custom.scss`. The darkmode toggle plugin is disabled.

## Deployment

Pushes to `main` that touch `docs/**` run `.github/workflows/deploy-docs.yml`, which builds and publishes `docs/public/` to the `gh-pages` branch.

Enable GitHub Pages: **Settings → Pages → Deploy from branch `gh-pages` / root**.
