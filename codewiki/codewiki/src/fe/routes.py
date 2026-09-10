#!/usr/bin/env python3
"""
FastAPI route handlers for the CodeWiki web application.
"""

from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import asdict

from traceback import format_exc

from fastapi import Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .models import JobStatus, JobStatusResponse
from .github_processor import GitHubRepoProcessor
from .background_worker import BackgroundWorker
from .cache_manager import CacheManager
from .templates import WEB_INTERFACE_TEMPLATE
from .template_utils import render_template
from .config import WebAppConfig
from codewiki.src.utils import file_manager


class WebRoutes:
    """Handles all web routes for the application."""
    
    def __init__(self, background_worker: BackgroundWorker, cache_manager: CacheManager):
        self.background_worker = background_worker
        self.cache_manager = cache_manager
    
    async def index_get(self, request: Request) -> HTMLResponse:
        """Main page with form for submitting GitHub repositories."""
        # Clean up old jobs before displaying
        # self.cleanup_old_jobs()
        
        # Get recent jobs (last 10)
        all_jobs = self.background_worker.get_all_jobs()
        recent_jobs = sorted(
            all_jobs.values(),
            key=lambda x: x.created_at,
            reverse=True
        )[:100]
        
        context = {
            "message": None,
            "message_type": None,
            "repo_url": "",
            "commit_id": "",
            "recent_jobs": recent_jobs
        }
        
        return HTMLResponse(content=render_template(WEB_INTERFACE_TEMPLATE, context))
    
    async def index_post(self, request: Request, repo_url: str = Form(...), commit_id: str = Form("")) -> HTMLResponse:
        """Handle repository submission."""
        # Clean up old jobs before processing
        self.cleanup_old_jobs()
        
        message = None
        message_type = None
        
        repo_url = repo_url.strip()
        commit_id = commit_id.strip() if commit_id else ""
        
        if not repo_url:
            message = "Please enter a GitHub repository URL"
            message_type = "error"
        elif not GitHubRepoProcessor.is_valid_github_url(repo_url):
            message = "Please enter a valid GitHub repository URL"
            message_type = "error"
        else:
            # Normalize the repo URL for comparison
            normalized_repo_url = self._normalize_github_url(repo_url)
            
            # Get repo info for job ID generation
            repo_info = GitHubRepoProcessor.get_repo_info(normalized_repo_url)
            job_id = self._repo_full_name_to_job_id(repo_info['full_name'])
            
            # Check if already in queue, processing, or recently failed
            existing_job = self.background_worker.get_job_status(job_id)
            recent_cutoff = datetime.now() - timedelta(minutes=WebAppConfig.RETRY_COOLDOWN_MINUTES)
            
            if existing_job:
                if existing_job.status in ['queued', 'processing']:
                    pass  # Will handle below
                elif existing_job.status == 'failed' and existing_job.created_at > recent_cutoff:
                    pass  # Will handle below
                else:
                    existing_job = None  # Job is old or completed, can reuse
            
            if existing_job:
                if existing_job.status in ['queued', 'processing']:
                    message = f"Repository is already being processed (Job ID: {existing_job.job_id})"
                else:
                    message = f"Repository recently failed processing. Please wait a few minutes before retrying (Job ID: {existing_job.job_id})"
                message_type = "error"
            else:
                # Check cache
                cached_docs = self.cache_manager.get_cached_docs(normalized_repo_url)
                if cached_docs and Path(cached_docs).exists():
                    message = "Documentation found in cache! Redirecting to view..."
                    message_type = "success"
                    # Create a dummy completed job for display
                    job = JobStatus(
                        job_id=job_id,
                        repo_url=normalized_repo_url,  # Use normalized URL
                        status='completed',
                        created_at=datetime.now(),
                        completed_at=datetime.now(),
                        docs_path=cached_docs,
                        progress="Retrieved from cache",
                        commit_id=commit_id if commit_id else None
                    )
                    self.background_worker.job_status[job_id] = job
                else:
                    # Add to queue
                    try:
                        job = JobStatus(
                            job_id=job_id,
                            repo_url=normalized_repo_url,  # Use normalized URL
                            status='queued',
                            created_at=datetime.now(),
                            progress="Waiting in queue...",
                            commit_id=commit_id if commit_id else None
                        )
                        
                        self.background_worker.add_job(job_id, job)
                        message = f"Repository added to processing queue! Job ID: {job_id}"
                        message_type = "success"
                        repo_url = ""  # Clear form
                        
                    except Exception as e:
                        message = f"Failed to add repository to queue: {str(e)}\n{format_exc()}"
                        message_type = "error"
        
        # Get recent jobs (last 10)
        all_jobs = self.background_worker.get_all_jobs()
        recent_jobs = sorted(
            all_jobs.values(),
            key=lambda x: x.created_at,
            reverse=True
        )
        
        context = {
            "message": message,
            "message_type": message_type,
            "repo_url": repo_url or "",
            "commit_id": commit_id or "",
            "recent_jobs": recent_jobs
        }
        
        return HTMLResponse(content=render_template(WEB_INTERFACE_TEMPLATE, context))
    
    async def local_job_post(self, body: dict) -> JSONResponse:
        """Register a job for a repository CodeOops already placed on the
        shared output volume (ZIP upload bridge), skipping the GitHub clone
        step entirely. Everything downstream — DocumentationGenerator,
        GET /api/job/{id}, output layout — is identical to the GitHub path.
        """
        job_id = body.get("job_id")
        local_path = body.get("local_path")

        if not job_id or not local_path:
            raise HTTPException(status_code=422, detail="job_id and local_path are required")

        # Path containment: local_path must resolve inside the shared output
        # volume. This endpoint must never be usable to point CodeWiki at an
        # arbitrary filesystem path.
        output_root = Path(WebAppConfig.OUTPUT_DIR).resolve()
        try:
            resolved_path = Path(local_path).resolve()
        except (OSError, RuntimeError):
            raise HTTPException(status_code=422, detail="Invalid local_path")

        if resolved_path != output_root and output_root not in resolved_path.parents:
            raise HTTPException(
                status_code=422, detail="local_path must be inside the shared output volume"
            )
        if not resolved_path.is_dir():
            raise HTTPException(
                status_code=422, detail="local_path does not exist or is not a directory"
            )

        existing_job = self.background_worker.get_job_status(job_id)
        if existing_job and existing_job.status in ('queued', 'processing'):
            return JSONResponse({"job_id": job_id, "status": existing_job.status}, status_code=202)

        job = JobStatus(
            job_id=job_id,
            repo_url=f"local://{job_id}",
            status='queued',
            created_at=datetime.now(),
            progress="Waiting in queue...",
            local_repo_path=str(resolved_path),
        )
        self.background_worker.add_job(job_id, job)

        return JSONResponse({"job_id": job_id, "status": "queued"}, status_code=202)

    async def get_job_status(self, job_id: str) -> JobStatusResponse:
        """API endpoint to get job status."""
        job = self.background_worker.get_job_status(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        return JobStatusResponse(**asdict(job))

    async def delete_job(self, job_id: str) -> JSONResponse:
        """API endpoint to forget one job (registry + jobs.json).

        The generated documentation directory on the shared volume is removed
        by CodeOops's own delete cascade; this only clears the engine's job
        list so it stops advertising a job whose docs are gone.
        """
        removed = self.background_worker.remove_job(job_id)
        return JSONResponse(
            {"job_id": job_id, "deleted": removed},
            status_code=200 if removed else 404,
        )
    
    async def view_docs(self, job_id: str) -> RedirectResponse:
        """View generated documentation."""
        job = self.background_worker.get_job_status(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        if job.status != 'completed' or not job.docs_path:
            raise HTTPException(status_code=404, detail="Documentation not available")
        
        docs_path = Path(job.docs_path)
        if not docs_path.exists():
            raise HTTPException(status_code=404, detail="Documentation files not found")
        
        # Redirect to the documentation viewer
        return RedirectResponse(url=f"/static-docs/{job_id}/", status_code=status.HTTP_302_FOUND)
    
    async def serve_generated_docs(self, job_id: str, filename: str = "overview.md") -> HTMLResponse:
        """Serve generated documentation files."""
        job = self.background_worker.get_job_status(job_id)
        docs_path = None
        repo_url = None
        
        if job:
            # Job status exists - use it
            if job.status != 'completed' or not job.docs_path:
                raise HTTPException(status_code=404, detail="Documentation not available")
            docs_path = Path(job.docs_path)
            repo_url = job.repo_url
        else:
            # No job status - try to find documentation in cache by job_id
            # Convert job_id back to repo full name and construct potential paths
            repo_full_name = self._job_id_to_repo_full_name(job_id)
            potential_repo_url = f"https://github.com/{repo_full_name}"
            
            # Check if documentation exists in cache
            cached_docs = self.cache_manager.get_cached_docs(potential_repo_url)
            if cached_docs and Path(cached_docs).exists():
                docs_path = Path(cached_docs)
                repo_url = potential_repo_url
                
                # Recreate job status for consistency
                job = JobStatus(
                    job_id=job_id,
                    repo_url=potential_repo_url,
                    status='completed',
                    created_at=datetime.now(),
                    completed_at=datetime.now(),
                    docs_path=cached_docs,
                    progress="Loaded from cache",
                    commit_id=None  # No commit info available from cache
                )
                self.background_worker.job_status[job_id] = job
                self.background_worker.save_job_statuses()
            else:
                raise HTTPException(status_code=404, detail="Documentation not found")
        
        if not docs_path or not docs_path.exists():
            raise HTTPException(status_code=404, detail="Documentation files not found")
        
        # Load module tree
        module_tree = None
        module_tree_file = docs_path / "module_tree.json"
        if module_tree_file.exists():
            try:
                module_tree = file_manager.load_json(module_tree_file)
            except Exception:
                pass
        
        # Load metadata
        metadata = None
        metadata_file = docs_path / "metadata.json"
        if metadata_file.exists():
            try:
                metadata = file_manager.load_json(metadata_file)
            except Exception:
                pass
        
        # Serve the requested file
        file_path = docs_path / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"File {filename} not found")
        
        try:
            content = file_manager.load_text(file_path)
            
            # Convert markdown to HTML (reuse from visualise_docs.py)
            from .visualise_docs import markdown_to_html, get_file_title
            from .templates import DOCS_VIEW_TEMPLATE
            
            html_content = markdown_to_html(content)
            title = get_file_title(file_path)
            
            context = {
                "repo_name": repo_url.split("/")[-1],
                "title": title,
                "content": html_content,
                "navigation": module_tree,
                "current_page": filename,
                "job_id": job_id,
                "metadata": metadata
            }
            
            return HTMLResponse(content=render_template(DOCS_VIEW_TEMPLATE, context))
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading {filename}: {e}\n{format_exc()}")
    
    def _normalize_github_url(self, url: str) -> str:
        """Normalize GitHub URL for consistent comparison."""
        try:
            # Get repo info to standardize the URL format
            repo_info = GitHubRepoProcessor.get_repo_info(url)
            return f"https://github.com/{repo_info['full_name']}"
        except Exception:
            # Fallback to basic normalization
            return url.rstrip('/').lower()
    
    def _repo_full_name_to_job_id(self, full_name: str) -> str:
        """Convert repo full name to URL-safe job ID."""
        return full_name.replace('/', '--')
    
    def _job_id_to_repo_full_name(self, job_id: str) -> str:
        """Convert job ID back to repo full name."""
        return job_id.replace('--', '/')
    
    def cleanup_old_jobs(self):
        """Clean up old job status entries."""
        cutoff = datetime.now() - timedelta(hours=WebAppConfig.JOB_CLEANUP_HOURS)
        all_jobs = self.background_worker.get_all_jobs()
        expired_jobs = [
            job_id for job_id, job in all_jobs.items()
            if job.created_at < cutoff and job.status in ['completed', 'failed']
        ]
        
        for job_id in expired_jobs:
            if job_id in self.background_worker.job_status:
                del self.background_worker.job_status[job_id]