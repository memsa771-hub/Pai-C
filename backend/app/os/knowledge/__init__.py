"""Knowledge: sourced facts behind a port. Slice 1 seeds them by hand; Slice 2 researches them
(fields defined by per-route research profiles)."""

from app.os.knowledge.port import Fact, FactStatus, KnowledgePort
from app.os.knowledge.profile import PROFILE_DIR, ProfileError, ResearchProfile, load_profile_dir, reading_model
from app.os.knowledge.seed import SEED_DIR, load_seed
from app.os.knowledge.store import SqlKnowledge

__all__ = ["PROFILE_DIR", "SEED_DIR", "Fact", "FactStatus", "KnowledgePort", "ProfileError", "ResearchProfile",
           "SqlKnowledge", "load_profile_dir", "load_seed", "reading_model"]
