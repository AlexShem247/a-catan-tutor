from abc import ABC, abstractmethod
from typing import Any


class BoardDisplaySource(ABC):
    @abstractmethod
    def get_ports(self) -> Any:
        """Return the board ports for display."""
        ...

    @abstractmethod
    def get_all_edges(self) -> Any:
        """Return all board edges for display."""
        ...

    @abstractmethod
    def get_all_vertices(self) -> Any:
        """Return all board vertices for display."""
        ...

    @abstractmethod
    def get_all_hexes(self) -> Any:
        """Return all board hexes for display."""
        ...

    @abstractmethod
    def get_bank_resources(self) -> Any:
        """Return the bank resource counts for display."""
        ...

    @abstractmethod
    def get_development_deck(self) -> Any:
        """Return the development deck for display."""
        ...

    @abstractmethod
    def get_all_players(self) -> Any:
        """Return all players for display."""
        ...
