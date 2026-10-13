# -*- coding: utf-8 -*-
"""Durable background jobs backed by PostgreSQL.

Deliberately generic — this is not a memory subsystem. Memory is the first
consumer (`memory.*` system capabilities), but the
queue itself knows nothing about memory and any future job type can use it.

Operator runs use this same durable queue; claimed jobs survive process
restarts and reuse the existing execution_runs row.
"""

from .service import BackgroundJobService, JobHandlerRegistry, job_handlers

__all__ = ["BackgroundJobService", "JobHandlerRegistry", "job_handlers"]
