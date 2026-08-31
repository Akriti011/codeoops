"""API schema for aggregate dashboard statistics.

Every field here is a real count computed at request time from the
repository and job stores — nothing is estimated, cached-and-stale, or
padded to look non-empty. An empty deployment reports zeros.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class JobStatusCounts(BaseModel):
    """Job counts collapsed to the three states the dashboard distinguishes.
    ``in_progress`` merges SUBMITTING/GENERATING/RETRIEVING — the dashboard
    doesn't need CodeOops's internal phase granularity, just whether a job
    is done, still running, or failed.
    """

    completed: int = Field(ge=0)
    in_progress: int = Field(ge=0)
    failed: int = Field(ge=0)


class DailyJobCounts(BaseModel):
    """One calendar day's (UTC) job counts, by each job's *current* status.

    Not a historical record — a job that completed today but was created
    yesterday counts toward yesterday's ``completed``, using its status as
    of this request. The store doesn't retain a status history to report
    otherwise.
    """

    date: str = Field(description="ISO 8601 date (YYYY-MM-DD), UTC.")
    completed: int = Field(ge=0)
    in_progress: int = Field(ge=0)
    failed: int = Field(ge=0)


class StatsResponse(BaseModel):
    repository_count: int = Field(ge=0)
    repository_count_added_last_7d: int = Field(ge=0)
    job_counts: JobStatusCounts
    job_counts_added_last_7d: JobStatusCounts
    jobs_per_day: list[DailyJobCounts] = Field(
        description="Last 7 UTC calendar days, oldest first, including today."
    )
