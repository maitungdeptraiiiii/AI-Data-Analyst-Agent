import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver


@dataclass
class GraphRuntime:
    graph: Any
    connection: sqlite3.Connection

    def close(self) -> None:
        self.connection.close()


def create_checkpointer(path: Path) -> tuple[SqliteSaver, sqlite3.Connection]:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    checkpointer = SqliteSaver(connection)
    checkpointer.setup()
    return checkpointer, connection
