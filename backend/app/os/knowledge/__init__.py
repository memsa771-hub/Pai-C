"""Knowledge: sourced facts behind a port. Slice 1 seeds them by hand; Slice 2 researches them."""

from app.os.knowledge.port import Fact, FactStatus, KnowledgePort
from app.os.knowledge.seed import SEED_DIR, load_seed
from app.os.knowledge.store import SqlKnowledge

__all__ = ["SEED_DIR", "Fact", "FactStatus", "KnowledgePort", "SqlKnowledge", "load_seed"]
