/* ── highlight.js ───────────────────────────────────────────── */
hljs.highlightAll();

/* ── Active nav link ────────────────────────────────────────── */
(function () {
  const page = location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.nav-link').forEach(a => {
    if (a.getAttribute('href') === page) a.classList.add('active');
  });
})();

/* ── Sidebar toggle ─────────────────────────────────────────── */
const sidebar    = document.getElementById('sidebar');
const overlay    = document.getElementById('overlay');
const sidebarBtn = document.getElementById('sidebarBtn');

function closeSidebar() {
  sidebar?.classList.remove('open');
  overlay?.classList.remove('visible');
}

sidebarBtn?.addEventListener('click', () => {
  sidebar.classList.toggle('open');
  overlay.classList.toggle('visible');
});
overlay?.addEventListener('click', closeSidebar);

/* Close sidebar on nav-link click (mobile) */
document.querySelectorAll('.nav-link').forEach(a => {
  a.addEventListener('click', () => {
    if (window.innerWidth <= 768) closeSidebar();
  });
});

/* ── Search index ───────────────────────────────────────────── */
const PAGES = [
  { title: 'Introduction',   url: 'index.html',          section: 'Getting Started' },
  { title: 'Quick Start',    url: 'quickstart.html',     section: 'Getting Started' },
  { title: 'Core Concepts',  url: 'concepts.html',       section: 'Concepts'        },
  { title: 'API Reference',  url: 'api-reference.html',  section: 'Reference'       },
  { title: 'Python SDK',     url: 'sdk-python.html',     section: 'Reference'       },
  { title: 'TypeScript SDK', url: 'sdk-typescript.html', section: 'Reference'       },
  { title: 'MCP Server',     url: 'mcp.html',            section: 'Reference'       },
  { title: 'Self-Hosting',   url: 'self-hosting.html',   section: 'Deployment'      },
  { title: 'Integrations',   url: 'integrations.html',   section: 'Integrations'    },
];

const searchInput = document.getElementById('docsSearch');
const searchDrop  = document.getElementById('searchDrop');
let searchIndex   = null;

function buildIndex() {
  const idx = PAGES.map(p => ({ ...p }));
  document.querySelectorAll('h2[id], h3[id]').forEach(h => {
    idx.push({
      title:   h.textContent.trim(),
      url:     '#' + h.id,
      section: 'On this page',
    });
  });
  return idx;
}

function renderResults(results, q) {
  if (!results.length) {
    searchDrop.innerHTML = `<div class="search-empty">No results for "<strong>${q}</strong>"</div>`;
  } else {
    searchDrop.innerHTML = results.slice(0, 9).map(r =>
      `<a href="${r.url}" class="search-result">
        <span class="search-result-section">${r.section}</span>
        <span class="search-result-title">${r.title}</span>
       </a>`
    ).join('');
  }
  searchDrop.classList.remove('hidden');
}

searchInput?.addEventListener('focus', () => {
  if (!searchIndex) searchIndex = buildIndex();
});

searchInput?.addEventListener('input', () => {
  if (!searchIndex) searchIndex = buildIndex();
  const q = searchInput.value.trim().toLowerCase();
  if (!q) { searchDrop.classList.add('hidden'); return; }
  const results = searchIndex.filter(r => r.title.toLowerCase().includes(q));
  renderResults(results, q);
});

document.addEventListener('click', e => {
  if (!searchInput?.contains(e.target) && !searchDrop?.contains(e.target)) {
    searchDrop?.classList.add('hidden');
  }
});

searchInput?.addEventListener('keydown', e => {
  if (e.key === 'Escape') searchDrop?.classList.add('hidden');
});
