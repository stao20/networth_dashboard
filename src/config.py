from enum import StrEnum

from utils.db import SupabaseHandler, SQLiteHandler


class Environment(StrEnum):
    PROD = "prod"
    DEV = "dev"


class Config:
    ENV = Environment.PROD
    DB_HANDLER = SupabaseHandler() if ENV == Environment.PROD else SQLiteHandler()

    @classmethod
    def is_dev(cls):
        return cls.ENV == Environment.DEV

    @classmethod
    def is_prod(cls):
        return cls.ENV == Environment.PROD
