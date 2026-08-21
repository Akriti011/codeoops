# CodeOops frontend

Angular SPA for CodeOops. See the [root README](../README.md) for the full
picture.

## Run

```bash
npm install
npm start          # http://localhost:4200
```

The dev server calls `http://127.0.0.1:8000/api/v1`. Start the backend first:

```bash
cd ../backend && uvicorn app.main:app --reload --port 8000
```

## Test

```bash
npm test           # interactive
npm run test:ci    # headless single run
```

## Build

```bash
npm run build      # → dist/codeoops
```

## Conventions

- **Standalone components everywhere.** No NgModules.
- **`ApiClient` is the only URL builder.** Components call domain services
  (`RepositoryService`, `HealthService`); those call `ApiClient`; `ApiClient`
  reads `API_BASE_URL`, which is provided once from `src/environments/`.
- **Errors are typed.** `apiErrorInterceptor` converts every `HttpErrorResponse`
  into an `ApiError` and re-throws. Nothing swallows an error, and no code path
  uses `alert()`.
- **States are explicit.** `WorkflowState` is the shared vocabulary:
  `IDLE · SUBMITTING · READY · GENERATING · COMPLETED · FAILED · NOT_GENERATED`.
- **The reader stays empty.** `documentation-viewer.component.ts` renders an
  explicit empty state when there is no artifact. It never renders substitute
  prose, sample Markdown or a preview of what documentation might look like.
