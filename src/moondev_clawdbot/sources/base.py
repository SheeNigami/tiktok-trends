from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from ..models import Item


class Source(ABC):
    name: str

    @abstractmethod
    def fetch(self) -> list[Item]:
        raise NotImplementedError


def source_names() -> list[str]:
    return ["tiktok", "hn", "rss", "reddit", "x_mock"]
