from collections import deque
from dataclasses import dataclass


@dataclass
class FrontierItem:
    url: str
    depth: int
    parent: str | None = None


class URLFrontier:
    def __init__(self, seed_urls: list[str], max_depth: int) -> None:
        self.queue = deque(FrontierItem(url=s, depth=0) for s in seed_urls)
        self.max_depth = max_depth
        self.visited: set[str] = set()

    def has_next(self) -> bool:
        return len(self.queue) > 0

    def next(self) -> FrontierItem:
        return self.queue.popleft()

    def add(self, items: list[FrontierItem]) -> None:
        for item in items:
            if item.depth > self.max_depth:
                continue
            if item.url in self.visited:
                continue
            self.queue.append(item)

    def mark_visited(self, url: str) -> None:
        self.visited.add(url)
