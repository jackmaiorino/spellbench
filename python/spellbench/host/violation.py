"""A live-validation violation (spec 11.3): the rule and a host-written detail."""

from __future__ import annotations

from ..errors import ProtocolError

RULES = tuple(f"V{number}" for number in range(1, 11))


class ValidatorViolation(ProtocolError):
    def __init__(self, rule: str, detail: str) -> None:
        if rule not in RULES:
            raise ValueError(f"unknown validator rule {rule!r}")
        super().__init__(f"{rule}: {detail}")
        self.rule = rule
        self.detail = detail

    def __reduce__(self) -> tuple:
        return (type(self), (self.rule, self.detail))
