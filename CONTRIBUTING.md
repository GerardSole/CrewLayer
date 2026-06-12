# Contributing to CrewLayer

Thank you for taking the time to contribute — it genuinely means a lot.
CrewLayer is a project built for developers by developers, and every contribution
makes it better for everyone building AI agents with it.
Whether you fix a typo, add a test, or implement a whole new feature, you're welcome here.

---

## Ways to contribute

You don't need to write code to contribute. Anything below helps:

- **Report a bug** — open an issue using the [bug report template][bug-template].
  The more detail you include (steps to reproduce, OS, version), the faster it gets fixed.
- **Suggest a feature** — start a [discussion][discussions] so we can talk through it
  before anyone writes code.
- **Improve the docs** — fix typos, clarify a confusing section, add a missing example.
  Documentation PRs are always welcome and get merged fast.
- **Add an example** — drop a script in `examples/` showing CrewLayer working with a
  framework or use-case that isn't covered yet.
- **Write tests** — increasing test coverage is one of the most valuable things you can do.
  Look for code paths that aren't covered in `tests/`.
- **Implement a feature** — check the [open issues][issues] for ideas, or propose your
  own via a discussion first if it's a larger change.

[bug-template]: https://github.com/GerardSole/CrewLayer/issues/new?template=bug_report.md
[discussions]: https://github.com/GerardSole/CrewLayer/discussions
[issues]: https://github.com/GerardSole/CrewLayer/issues

---

## Setting up your development environment

Follow these steps exactly — no prior knowledge of the project is assumed.

### Prerequisites

- Python 3.12 or newer
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for PostgreSQL + Redis)
- An [Anthropic API key](https://console.anthropic.com/) (for embeddings and memory extraction)
- Git

### Step-by-step setup

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/<your-username>/CrewLayer
cd CrewLayer

# 2. Create a virtual environment and install all dependencies
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 3. Copy the example environment file and fill in your values
cp .env.example .env
# Open .env and set:
#   ANTHROPIC_API_KEY=sk-ant-...
#   DATABASE_URL=postgresql+asyncpg://crewlayer:crewlayer@localhost/crewlayer
#   REDIS_URL=redis://localhost:6379
#   SECRET_KEY=any-random-string-here

# 4. Start the database and Redis
docker compose up -d

# 5. Run the database migrations
alembic upgrade head

# 6. (Optional) Seed demo data
python scripts/seed.py
# Prints a demo tenant + API key you can use right away

# 7. Start the dev server
uvicorn main:app --reload
```

The API docs are now at **http://localhost:8000/docs**.

### Verify everything works

```bash
pytest tests/ -v
```

All tests should pass. They need PostgreSQL and Redis running (`docker compose up -d`).
Each test creates its own tenant and cleans up after itself — nothing is left behind.

```bash
# Run a single file while developing
pytest tests/test_memory.py -v

# Run with coverage
pytest tests/ --cov=crewlayer --cov-report=term-missing
```

---

## Making a pull request

```bash
# 1. Create a branch — use feat/ for new features, fix/ for bug fixes
git checkout -b feat/my-feature
# or
git checkout -b fix/the-bug-description

# 2. Make your changes
# ... edit files ...

# 3. Write tests for what you changed (see "What makes a PR accepted" below)

# 4. Run linting and type checking
ruff check . --fix         # auto-fixes safe issues
mypy crewlayer/            # must pass with zero errors

# 5. Run the full test suite
pytest tests/ -v           # all tests must pass

# 6. Commit with a clear message
git add .
git commit -m "feat: add X to Y"   # or "fix: ..." / "docs: ..." / "test: ..."

# 7. Push and open a PR toward the `dev` branch
git push origin feat/my-feature
```

Then open a pull request on GitHub from your branch to `dev`.
In the PR description, explain **what** the change does and **why** it's needed.
The pull request template will guide you through the checklist.

---

## What makes a PR accepted

These are the things we check:

- **Tests** — every change to behaviour needs at least one test that fails without the change
  and passes with it. We won't merge code that reduces coverage.
- **Ruff and mypy pass** — `ruff check .` and `mypy crewlayer/` must both return zero errors.
  The project uses strict mypy.
- **One change per PR** — each PR should do exactly one thing. If you find a bug while
  implementing a feature, fix it in a separate PR. Smaller PRs get reviewed and merged much faster.
- **Clear description** — tell us what you changed and why, not just what files you touched.
  If it closes an issue, include `Closes #123`.
- **No breaking API changes without versioning** — all public endpoints live under `/v1/`.
  A breaking change requires a new `/v2/` prefix and keeping the old version working.
- **SDK parity** — if you change the REST API, update both the Python SDK (`sdk/crewlayer/`)
  and the TypeScript SDK (`sdk-typescript/src/resources/`) in the same PR.
- **Business logic in `core/`** — route handlers stay thin. No database queries or business
  logic in `crewlayer/api/routes/`.

---

## Good first issues

Not sure where to start? Look for issues labelled
**[`good first issue`](https://github.com/GerardSole/CrewLayer/issues?q=is%3Aopen+label%3A%22good+first+issue%22)**
on the issue tracker. These are tasks that don't require deep knowledge of the codebase
and have clear acceptance criteria.

Some ideas that are always welcome:
- Adding examples in `examples/` for frameworks not yet covered
- Improving error messages to be more actionable
- Adding docstrings to functions that lack them
- Increasing test coverage for edge cases

We commit to reviewing all pull requests within **48 hours** of submission.
If you haven't heard back in two days, feel free to ping in the PR thread.

---

## Code of conduct

CrewLayer is a welcoming project. Be respectful and kind — to other contributors,
to maintainers, and to people raising issues or asking questions.
There are no stupid questions, especially if you're new to the codebase.
We want this project to be a place where anyone feels comfortable contributing,
regardless of experience level, background, or identity.

---

## Credits

Every contributor to CrewLayer is recognised in the project README.
Open a PR, get it merged, and your name goes in the list — it's that simple.
