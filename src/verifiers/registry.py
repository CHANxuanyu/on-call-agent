"""Simple in-memory registry for verifiers."""

from __future__ import annotations

from dataclasses import dataclass, field

from verifiers.base import Verifier, VerifierDefinition


@dataclass(slots=True)
class VerifierRegistry:
    """Stores verifier implementations by name."""

    _verifiers: dict[str, Verifier] = field(default_factory=dict)

    def register(self, verifier: Verifier) -> None:
        name = verifier.definition.name
        if name in self._verifiers:
            msg = f"verifier already registered: {name}"
            raise ValueError(msg)
        self._verifiers[name] = verifier

    def get(self, name: str) -> Verifier | None:
        return self._verifiers.get(name)

    def definitions(self) -> tuple[VerifierDefinition, ...]:
        return tuple(verifier.definition for _, verifier in sorted(self._verifiers.items()))
