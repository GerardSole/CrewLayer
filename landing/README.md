# CrewLayer Landing Page

Static landing page for CrewLayer. Single `index.html` with no build step required.

## Deploy to Vercel

### Option A — Deploy just the landing folder

1. Copy the `landing/` folder to a new repo (or use this monorepo):

```bash
# From a fresh repo containing only landing/
git init crewlayer-landing
cp -r landing/ crewlayer-landing/
cd crewlayer-landing && git add . && git commit -m "init"
gh repo create crewlayer-landing --public --push
```

2. Go to [vercel.com/new](https://vercel.com/new), import the repo.

3. In **Build & Output Settings**:
   - Framework Preset: **Other**
   - Build Command: _(leave empty)_
   - Output Directory: `.` (dot — the root)

4. Click **Deploy**. Done.

### Option B — Deploy from this monorepo

1. Import this repo into Vercel.

2. In **Build & Output Settings**:
   - Framework Preset: **Other**
   - Build Command: _(leave empty)_
   - Output Directory: `landing`

3. Click **Deploy**.

Vercel will serve `landing/index.html` at the root URL automatically.

### Custom domain

In Vercel → Project → Settings → Domains, add `crewlayer.dev` (or your domain).

## Local preview

Open directly in the browser — no server needed:

```bash
open landing/index.html   # macOS
start landing/index.html  # Windows
```

Or with any static server:

```bash
npx serve landing
# → http://localhost:3000
```

## Updating content

Everything is in `landing/index.html`:

- **Colors / palette** — `:root` CSS variables at the top of `<style>`
- **Copy** — edit the HTML sections directly
- **Code snippets** — update `<code>` blocks; highlight.js re-highlights on load
- **Links** — search for `href="#"` placeholders and replace with real URLs

## OG image

Add a `landing/og.png` (1200×630) and it will be picked up by the `og:image` meta tag.
