# CodeOops API

FastAPI orchestration layer for CodeOops. See the [root README](../README.md)
for the full picture.

## Run

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

- API: <http://127.0.0.1:8000/api/v1>
- OpenAPI UI: <http://127.0.0.1:8000/docs>

## Test

```bash
pytest
```

## Layers

| Package | Responsibility | Must not |
|---|---|---|
| `api/routes` | HTTP in, HTTP out | contain business logic |
| `api/deps.py` | choose implementations | be bypassed by routes |
| `services` | all behaviour | know about HTTP |
| `repositories` | storage port + adapter | leak storage types upward |
| `providers` | the external-engine port | contain an implementation |
| `models` | domain objects | depend on Pydantic schemas |
| `schemas` | wire contracts | contain behaviour |

## The CodeWiki boundary

`app/providers/documentation_provider.py` defines `DocumentationProvider` and
nothing else. `get_documentation_provider()` returns `None`, so:

- reads report `NOT_GENERATED` with a `null` artifact, and
- generation requests fail with `501 DOCUMENTATION_PROVIDER_NOT_CONFIGURED`.

`tests/test_codewiki_boundary.py` fails the build if an LLM SDK is imported, if a
documentation-generation function appears, if Markdown documents get embedded in
the source, or if a concrete provider is added without going through the port.
