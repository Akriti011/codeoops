# CodeWiki — vendored from the original source tree (see codeoops/README.md
# for provenance) with this repo's own patches already applied on disk:
# single-overview mode, the evidence extractor, the rewritten HLD prompt,
# resource bounds (num_ctx/output cap/timeout/max_retries=0), and the ZIP
# upload local-job bridge. Matches codewiki:0.0.1's own build recipe —
# native arm64 on Apple Silicon, no forced linux/amd64.
FROM python:3.12-slim

WORKDIR /app

# build-essential: some pinned deps (e.g. fastuuid) have no prebuilt arm64
# wheel for this Python version and build a small Rust extension from
# source via maturin — that needs a C linker present, not just Rust itself
# (which maturin already bundles on demand).
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    nodejs \
    npm \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY codewiki ./codewiki
COPY img ./img
COPY pyproject.toml .
COPY README.md .

RUN mkdir -p output/cache output/temp output/docs output/dependency_graphs output/uploads

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

CMD ["python", "codewiki/run_web_app.py", "--host", "0.0.0.0", "--port", "8000"]
