from __future__ import annotations


class SemanticChromaStore:
    """Optional semantic backend behind a feature flag."""

    def __init__(self) -> None:
        raise NotImplementedError("Chroma backend is optional and not implemented in phase 1")
