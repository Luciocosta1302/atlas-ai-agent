"""Memória das conversas: checkpointer do LangGraph + registro de conversas.

- O **checkpointer** (``AsyncSqliteSaver``) guarda o estado do grafo
  (mensagens) de cada conversa, separado por ``thread_id``.
- O **registro de conversas** (tabela ``threads``) guarda quando cada
  conversa foi criada e usada pela última vez. Ele serve para:
    1. aceitar apenas ``thread_id``s criados pelo próprio servidor;
    2. apagar conversas inativas há mais de ``CONVERSATION_TTL_HOURS``.
"""

from __future__ import annotations

import logging
import secrets
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

logger = logging.getLogger(__name__)

Clock = Callable[[], float]


def new_thread_id() -> str:
    """Gera um id imprevisível (128 bits aleatórios em hexadecimal)."""
    return secrets.token_hex(16)


class ThreadRepository(Protocol):
    """Registro de conversas. Duas implementações: SQLite e memória (testes)."""

    async def create(self) -> str: ...
    async def exists(self, thread_id: str) -> bool: ...
    async def touch(self, thread_id: str) -> None: ...
    async def delete(self, thread_id: str) -> None: ...
    async def expired(self, ttl_seconds: float) -> list[str]: ...


class InMemoryThreadRepository:
    """Implementação em memória, usada nos testes."""

    def __init__(self, clock: Clock = time.time) -> None:
        self._last_used: dict[str, float] = {}
        self._clock = clock

    async def create(self) -> str:
        thread_id = new_thread_id()
        self._last_used[thread_id] = self._clock()
        return thread_id

    async def exists(self, thread_id: str) -> bool:
        return thread_id in self._last_used

    async def touch(self, thread_id: str) -> None:
        if thread_id in self._last_used:
            self._last_used[thread_id] = self._clock()

    async def delete(self, thread_id: str) -> None:
        self._last_used.pop(thread_id, None)

    async def expired(self, ttl_seconds: float) -> list[str]:
        limit = self._clock() - ttl_seconds
        return [tid for tid, last in self._last_used.items() if last < limit]


class SqliteThreadRepository:
    """Implementação em SQLite, no mesmo banco do checkpointer."""

    def __init__(self, conn: aiosqlite.Connection, clock: Clock = time.time) -> None:
        self._conn = conn
        self._clock = clock

    async def setup(self) -> None:
        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS threads (
                thread_id    TEXT PRIMARY KEY,
                created_at   REAL NOT NULL,
                last_used_at REAL NOT NULL
            )
            """
        )
        await self._conn.commit()

    async def create(self) -> str:
        thread_id = new_thread_id()
        now = self._clock()
        # Consultas sempre parametrizadas (?) para evitar SQL injection.
        await self._conn.execute(
            "INSERT INTO threads (thread_id, created_at, last_used_at) VALUES (?, ?, ?)",
            (thread_id, now, now),
        )
        await self._conn.commit()
        return thread_id

    async def exists(self, thread_id: str) -> bool:
        async with self._conn.execute(
            "SELECT 1 FROM threads WHERE thread_id = ?", (thread_id,)
        ) as cursor:
            return await cursor.fetchone() is not None

    async def touch(self, thread_id: str) -> None:
        await self._conn.execute(
            "UPDATE threads SET last_used_at = ? WHERE thread_id = ?", (self._clock(), thread_id)
        )
        await self._conn.commit()

    async def delete(self, thread_id: str) -> None:
        await self._conn.execute("DELETE FROM threads WHERE thread_id = ?", (thread_id,))
        await self._conn.commit()

    async def expired(self, ttl_seconds: float) -> list[str]:
        async with self._conn.execute(
            "SELECT thread_id FROM threads WHERE last_used_at < ?",
            (self._clock() - ttl_seconds,),
        ) as cursor:
            return [row[0] for row in await cursor.fetchall()]


@dataclass(frozen=True)
class ConversationStore:
    """Agrupa as duas partes da memória para facilitar a injeção."""

    checkpointer: BaseCheckpointSaver
    threads: ThreadRepository

    async def delete(self, thread_id: str) -> None:
        await self.checkpointer.adelete_thread(thread_id)
        await self.threads.delete(thread_id)

    async def purge_expired(self, ttl_seconds: float) -> int:
        """Apaga as conversas inativas há mais de ``ttl_seconds``."""
        expired = await self.threads.expired(ttl_seconds)
        for thread_id in expired:
            await self.delete(thread_id)
        if expired:
            logger.info("%d conversa(s) expirada(s) apagada(s)", len(expired))
        return len(expired)


@asynccontextmanager
async def open_sqlite_store(database_path: Path) -> AsyncIterator[ConversationStore]:
    """Abre (e fecha ao final) o banco SQLite da memória."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(database_path) as conn:
        checkpointer = AsyncSqliteSaver(conn)
        await checkpointer.setup()
        threads = SqliteThreadRepository(conn)
        await threads.setup()
        yield ConversationStore(checkpointer=checkpointer, threads=threads)
