from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CancellationToken:
    _cancelled: bool = False
    reason: str | None = None

    def cancel(self, reason: str | None = None) -> None:
        self._cancelled = True
        self.reason = reason

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise RuntimeError(self.reason or "operation cancelled")


@dataclass
class RunContext:
    cancellation: CancellationToken = field(default_factory=CancellationToken)
