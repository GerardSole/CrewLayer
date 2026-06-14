# CrewLayer Docs

Static documentation site for [CrewLayer](https://github.com/GerardSole/CrewLayer). Built with vanilla HTML + CSS + JS. No build step required.

## Pages

| File | Section | Description |
|------|---------|-------------|
| `index.html` | Introduction | Architecture overview, what CrewLayer gives you, tech stack |
| `quickstart.html` | Quick Start | 5-step guide from clone to first memory recall |
| `concepts.html` | Core Concepts | Tenants, agents, memory, actions, sessions, episodes, blackboard |
| `api-reference.html` | Reference | All REST endpoints with method badges |
| `sdk-python.html` | Reference | Python SDK — client, memory, actions, LangChain, AutoGen |
| `sdk-typescript.html` | Reference | TypeScript SDK — client, SSE streaming, Vercel AI adapter |
| `mcp.html` | Reference | MCP Server — stdio/SSE transports, Claude config, all 9 tools |
| `self-hosting.html` | Deployment | Docker Compose, env vars, nginx, SSL, backups, upgrading |
| `integrations.html` | Guides | LangChain, AutoGen, LlamaIndex, Vercel AI SDK examples |

## Deploying to Vercel

### Option A — Docs as a standalone site

1. Create a new Vercel project pointing to this repo (or a fork).
2. Set the **Root Directory** to `docs`.
3. Set **Framework Preset** to **Other**.
4. Set **Output Directory** to `.` (current directory — the HTML files are already the output).
5. Deploy. The site will be available at `https://docs.your-project.vercel.app`.

### Option B — Monorepo (docs + landing in one repo)

If you're deploying the landing page and docs from the same repo:

**Landing** (separate Vercel project):
- Root Directory: `landing`
- Output Directory: `.`

**Docs** (separate Vercel project):
- Root Directory: `docs`
- Output Directory: `.`

Then update the Docs link in `landing/index.html` to point to your docs domain.

### Option C — Subdirectory on the same domain

If you want `yourdomain.com/docs`:

1. Deploy docs as a Vercel project (Option A).
2. In your main site's `vercel.json`, add a rewrite:

```json
{
  "rewrites": [
    { "source": "/docs/:path*", "destination": "https://docs.yourdomain.vercel.app/:path*" }
  ]
}
```

## Local Development

No build step needed — just open any HTML file in your browser:

```bash
# Using Python's built-in server (from the docs/ directory)
cd docs
python -m http.server 3001
# → http://localhost:3001

# Using Node's serve package
npx serve docs -p 3001
```

The search and sidebar navigation work correctly when served over HTTP (not `file://`).

## Customizing

- **Colors and spacing**: edit the CSS variables at the top of `docs.css`.
- **Navigation structure**: update the `<nav class="sidebar-nav">` block inside each HTML file.
- **Search index**: the `PAGES` array in `docs.js` drives cross-page search. Update it when adding new pages.
- **Syntax highlighting theme**: swap the highlight.js CSS CDN link in each HTML `<head>`.
