"""Aggregate dashboard statistics.

Reads the repository and job stores directly and counts — no caching, no
persistence of its own. Every number is real and computed fresh per request;
see app/schemas/stats.py for what "real" means for the per-day breakdown.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.enums import JobStatus
from app.models.job import DocumentationJob
from app.repositories.job_repository import JobStore
from app.repositories.repository_repository import RepositoryStore
from app.schemas.stats import DailyJobCounts, JobStatusCounts, StatsResponse

_IN_PROGRESS_STATUSES = frozenset(
    {JobStatus.SUBMITTING, JobStatus.GENERATING, JobStatus.RETRIEVING}
)
_TREND_DAYS = 7


def _bucket(job: DocumentationJob) -> str | None:
    if job.status == JobStatus.COMPLETED:
        return "completed"
    if job.status == JobStatus.FAILED:
        return "failed"
    if job.status in _IN_PROGRESS_STATUSES:
        return "in_progress"
    return None


def _count_by_status(jobs: list[DocumentationJob]) -> JobStatusCounts:
    counts = {"completed": 0, "in_progress": 0, "failed": 0}
    for job in jobs:
        bucket = _bucket(job)
        if bucket is not None:
            counts[bucket] += 1
    return JobStatusCounts(**counts)


class StatsService:
    def __init__(self, repositories: RepositoryStore, jobs: JobStore) -> None:
        self._repositories = repositories
        self._jobs = jobs

    def get_stats(self) -> StatsResponse:
        now = datetime.now(UTC)
        week_ago = now - timedelta(days=7)

        repos = self._repositories.list()
        jobs = self._jobs.list_all()

        repo_count_last_7d = sum(1 for r in repos if r.created_at >= week_ago)
        job_counts_last_7d = _count_by_status([j for j in jobs if j.created_at >= week_ago])

        return StatsResponse(
            repository_count=len(repos),
            repository_count_added_last_7d=repo_count_last_7d,
            job_counts=_count_by_status(jobs),
            job_counts_added_last_7d=job_counts_last_7d,
            jobs_per_day=self._jobs_per_day(jobs, now),
        )

    def _jobs_per_day(
        self, jobs: list[DocumentationJob], now: datetime
    ) -> list[DailyJobCounts]:
        days = [
            (now - timedelta(days=offset)).date() for offset in range(_TREND_DAYS - 1, -1, -1)
        ]
        by_day: dict[str, dict[str, int]] = {
            day.isoformat(): {"completed": 0, "in_progress": 0, "failed": 0} for day in days
        }
        oldest = days[0]
        for job in jobs:
            job_date = job.created_at.astimezone(UTC).date()
            if job_date < oldest:
                continue
            key = job_date.isoformat()
            if key not in by_day:
                continue
            bucket = _bucket(job)
            if bucket is not None:
                by_day[key][bucket] += 1

        return [
            DailyJobCounts(date=day.isoformat(), **by_day[day.isoformat()]) for day in days
        ]
