from __future__ import annotations

import bisect


class Marks:
    """User marks plus auto-pick suggestions, both as sorted frame numbers."""

    def __init__(self, marked=(), suggested=()):
        self.marked: list[int] = sorted(set(marked))
        self.suggested: list[int] = sorted(set(suggested) - set(self.marked))

    def is_marked(self, n: int) -> bool:
        i = bisect.bisect_left(self.marked, n)
        return i < len(self.marked) and self.marked[i] == n

    def is_suggested(self, n: int) -> bool:
        i = bisect.bisect_left(self.suggested, n)
        return i < len(self.suggested) and self.suggested[i] == n

    def toggle(self, n: int) -> bool:
        """Toggle a user mark. A suggestion at n is accepted. Returns new state."""
        if self.is_marked(n):
            self.marked.remove(n)
            return False
        if self.is_suggested(n):
            self.suggested.remove(n)
        bisect.insort(self.marked, n)
        return True

    def remove(self, n: int) -> None:
        if self.is_marked(n):
            self.marked.remove(n)
        if self.is_suggested(n):
            self.suggested.remove(n)

    def accept(self, frames) -> None:
        for n in frames:
            if self.is_suggested(n):
                self.suggested.remove(n)
                bisect.insort(self.marked, n)

    def accept_all(self) -> None:
        self.accept(list(self.suggested))

    def set_suggestions(self, frames, replace: bool = True) -> None:
        current = set() if replace else set(self.suggested)
        self.suggested = sorted((current | set(frames)) - set(self.marked))

    def clear_suggestions(self) -> None:
        self.suggested = []

    def all(self) -> list[int]:
        return sorted(self.marked + self.suggested)

    def next_after(self, n: int, include_suggested: bool = True) -> int | None:
        frames = self.all() if include_suggested else self.marked
        i = bisect.bisect_right(frames, n)
        return frames[i] if i < len(frames) else None

    def prev_before(self, n: int, include_suggested: bool = True) -> int | None:
        frames = self.all() if include_suggested else self.marked
        i = bisect.bisect_left(frames, n)
        return frames[i - 1] if i > 0 else None

    def to_dict(self) -> dict:
        return {"marked": self.marked, "suggested": self.suggested}

    @classmethod
    def from_dict(cls, d: dict, frame_count: int) -> Marks:
        def ok(xs):
            return [int(x) for x in xs if 0 <= int(x) < frame_count]

        return cls(ok(d.get("marked", [])), ok(d.get("suggested", [])))
