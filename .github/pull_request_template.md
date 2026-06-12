## What does this PR do?

<!--
One or two sentences. What changed, and why?
If it closes an issue: "Closes #123"
-->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation / examples
- [ ] Tests
- [ ] Refactor (no behaviour change)

## How to test it

<!--
Steps someone can follow to verify this works.
Even for small changes, this helps reviewers.
-->

1.
2.

## Checklist

- [ ] I wrote or updated tests for every changed behaviour
- [ ] `pytest tests/ -v` passes with no failures
- [ ] `ruff check .` passes with no errors
- [ ] `mypy crewlayer/` passes with no errors
- [ ] If I changed the REST API: I updated the Python SDK (`sdk/crewlayer/`) and the TypeScript SDK (`sdk-typescript/src/resources/`)
- [ ] If I added a new public endpoint: there is at least one test covering the happy path and one error case
- [ ] If I changed database models: I created and reviewed an Alembic migration
- [ ] Documentation or docstrings updated where needed

## Screenshots / output (if relevant)

<!-- Paste terminal output, a diff of the API response, etc. -->
