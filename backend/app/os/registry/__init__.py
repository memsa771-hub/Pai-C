"""The registry of institutions, bodies, systems, tests, seat categories, calendars and the official lists they came
from (P2 spec §4.1; R-32, R-33, R-34)."""

from app.os.registry.coverage import Coverage, coverage_map, summarise
from app.os.registry.lists import OfficialListError, load_official_lists, parse_official_lists
from app.os.registry.model import KIND_PREFIX, RegistryEntry, known_region, slug
from app.os.registry.store import ListProgress, Recorded, RegistryError, RegistryStore

__all__ = ["KIND_PREFIX", "Coverage", "ListProgress", "OfficialListError", "Recorded", "RegistryEntry",
           "RegistryError", "RegistryStore", "coverage_map", "known_region", "load_official_lists",
           "parse_official_lists", "slug", "summarise"]
