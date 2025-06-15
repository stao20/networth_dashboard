from dataclasses import dataclass
from typing import Optional
from datetime import datetime

@dataclass
class User:
    id: str  # Google OAuth ID
    email: str
    name: str
    created_at: Optional[datetime] = None

@dataclass
class Category:
    id: Optional[str]
    user_id: str
    name: str
    created_at: Optional[datetime] = None

@dataclass
class Account:
    id: Optional[str]
    user_id: str
    category_id: str
    name: str
    created_at: Optional[datetime] = None

@dataclass
class AccountValue:
    id: Optional[str]
    account_id: str
    date: str
    value: float
    created_at: Optional[datetime] = None

@dataclass
class Pot:
    name: str
    initial: float = 0.0
    monthly: float = 0.0
    rate: float = 0.0