"""Offline defaults; tests may explicitly install their own fake hybrid index."""
import pytest
from app.memory import index


@pytest.fixture(autouse=True)
def offline_memory_index():
    previous = index._index
    index.set_memory_index(index.NullMemoryIndex())
    try:
        yield
    finally:
        index._index = previous
