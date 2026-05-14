from abc import ABC, abstractmethod
from typing import Any


class BoardDisplaySource(ABC):
    @abstractmethod
    def get_ports(self) -> Any:
        ...

    @abstractmethod
    def get_all_edges(self) -> Any:
        ...

    @abstractmethod
    def get_all_vertices(self) -> Any:
        ...

    @abstractmethod
    def get_all_hexes(self) -> Any:
        ...

    @abstractmethod
    def get_bank_resources(self) -> Any:
        ...

    @abstractmethod
    def get_development_deck(self) -> Any:
        ...

    @abstractmethod
    def get_all_players(self) -> Any:
        ...
