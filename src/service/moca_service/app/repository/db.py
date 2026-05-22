from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


class Database:
    def __init__(self, config: DbConfig):
        self.config = config

    def connect(self, *, autocommit: bool = True) -> Connection:
        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=autocommit,
        )

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.connect(autocommit=False) as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
