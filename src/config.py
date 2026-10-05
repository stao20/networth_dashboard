import os
from enum import StrEnum

from utils.db import SupabaseHandler, SQLiteHandler


class Environment(StrEnum):
    PROD = "prod"
    DEV = "dev"


def _make_db_handler():
    if os.environ.get("DEMO_SYNC") == "1":
        from utils.demo_db import DemoHandler

        return DemoHandler()
    if Config.ENV == Environment.PROD:
        return SupabaseHandler()
    return SQLiteHandler()


class Config:
    ENV = Environment.PROD
    DB_HANDLER = None  # set below after class body

    @classmethod
    def is_dev(cls):
        return cls.ENV == Environment.DEV

    @classmethod
    def is_prod(cls):
        return cls.ENV == Environment.PROD


Config.DB_HANDLER = _make_db_handler()
