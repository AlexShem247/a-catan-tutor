from typing import Any, Protocol


class BoardDisplaySource(Protocol):
    def get_ports(self) -> Any:
        ...

    def get_all_edges(self) -> Any:
        ...

    def get_all_vertices(self) -> Any:
        ...

    def get_all_hexes(self) -> Any:
        ...

    def get_bank_resources(self) -> Any:
        ...

    def get_development_deck(self) -> Any:
        ...

    def get_all_players(self) -> Any:
        ...
