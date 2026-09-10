#!/usr/bin/env python3
"""
CodeWiki Web Application

A web interface for users to submit GitHub repositories for documentation generation.
Features:
- Simple web form for GitHub repo URL input
- Background processing queue
- Cache system for generated documentation
- Job status tracking
"""

import argparse
import logging
import sys
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse

from .cache_manager import CacheManager
from .background_worker import BackgroundWorker
from .routes import WebRoutes
from .config import WebAppConfig

# uvicorn.run(..., log_level=...) below only configures uvicorn's OWN loggers
# ("uvicorn", "uvicorn.error", "uvicorn.access") — it never touches the root
# logger. Every module in this codebase logs via `logging.getLogger(__name__)`
# with no handler of its own, so with no root handler configured, Python's
# `logging` package falls back to `logging.lastResort`: a stderr handler
# fixed at WARNING. The practical effect, confirmed against real container
# logs: every `logger.info(...)` call in the documentation-generation pipeline
# (progress messages, timing, "single-shot overview written", etc.) was
# silently dropped, while `logger.warning`/`logger.error` calls came through
# fine — making real failures look like nothing had run at all. Configuring
# the root logger explicitly, before anything else in this process can log,
# fixes that for every module without touching each one individually.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)

# Initialize FastAPI app
app = FastAPI(
    title="CodeWiki", 
    description="Generate comprehensive documentation for any GitHub repository"
)

# Initialize components
cache_manager = CacheManager(
    cache_dir=WebAppConfig.CACHE_DIR, 
    cache_expiry_days=WebAppConfig.CACHE_EXPIRY_DAYS
)
background_worker = BackgroundWorker(
    cache_manager=cache_manager, 
    temp_dir=WebAppConfig.TEMP_DIR
)
web_routes = WebRoutes(background_worker=background_worker, cache_manager=cache_manager)


# Register routes
@app.get("/", response_class=HTMLResponse)
async def index_get(request: Request):
    """Main page with form for submitting GitHub repositories."""
    return await web_routes.index_get(request)


@app.post("/", response_class=HTMLResponse)
async def index_post(request: Request, repo_url: str = Form(...), commit_id: str = Form("")):
    """Handle repository submission."""
    return await web_routes.index_post(request, repo_url, commit_id)


@app.post("/api/local-job")
async def local_job_post(request: Request):
    """API endpoint for submitting a repository already extracted onto the
    shared output volume (ZIP upload bridge — see routes.WebRoutes.local_job_post)."""
    body = await request.json()
    return await web_routes.local_job_post(body)


@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    """API endpoint to get job status."""
    return await web_routes.get_job_status(job_id)


@app.delete("/api/job/{job_id}")
async def delete_job(job_id: str):
    """Forget one job — called by CodeOops when its repository is deleted."""
    return await web_routes.delete_job(job_id)


@app.get("/docs/{job_id}")
async def view_docs(job_id: str):
    """View generated documentation."""
    return await web_routes.view_docs(job_id)


@app.get("/static-docs/{job_id}/")
@app.get("/static-docs/{job_id}/{filename:path}")
async def serve_generated_docs(job_id: str, filename: str = "overview.md"):
    """Serve generated documentation files."""
    if not filename: 
        filename = "overview.md"
    return await web_routes.serve_generated_docs(job_id, filename)


def main():
    """Main function to run the web application."""
    import uvicorn
    
    parser = argparse.ArgumentParser(
        description="CodeWiki Web Application - Generate documentation for GitHub repositories"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=WebAppConfig.DEFAULT_HOST,
        help=f"Host to bind the server to (default: {WebAppConfig.DEFAULT_HOST})"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=WebAppConfig.DEFAULT_PORT,
        help=f"Port to run the server on (default: {WebAppConfig.DEFAULT_PORT})"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Run the server in debug mode"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development"
    )
    
    args = parser.parse_args()
    
    # Ensure required directories exist
    WebAppConfig.ensure_directories()
    
    # Start background worker
    background_worker.start()
    
    print(f"🚀 CodeWiki Web Application starting...")
    print(f"🌐 Server running at: http://{args.host}:{args.port}")
    print(f"📁 Cache directory: {WebAppConfig.get_absolute_path(WebAppConfig.CACHE_DIR)}")
    print(f"🗂️  Temp directory: {WebAppConfig.get_absolute_path(WebAppConfig.TEMP_DIR)}")
    print("\nPress Ctrl+C to stop the server")
    
    try:
        uvicorn.run(
            "fe.web_app:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level="debug" if args.debug else "info"
        )
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
        background_worker.stop()


if __name__ == "__main__":
    main()