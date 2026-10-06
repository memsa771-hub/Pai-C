"""Operational application planning, separate from canonical Student Profile."""
from fastapi import APIRouter

from . import calendar, catalog, plans, operations

router = APIRouter(prefix="/v1/application-workspace", tags=["Application Workspace"])
router.include_router(calendar.router)
router.include_router(catalog.router)
router.include_router(plans.router)
router.include_router(operations.router)
