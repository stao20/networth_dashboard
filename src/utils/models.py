from dataclasses import dataclass
from typing import Optional
from datetime import datetime, date as _date

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

@dataclass
class SimulationReport:
    id: Optional[str]
    user_id: str
    name: str
    report_data: dict
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class WeightPlan:
    id: Optional[str]
    user_id: str
    start_weight_kg: float
    target_weight_kg: float
    weekly_rate_kg: float
    daily_kcal_target: int
    weekly_exercise_min_target: int
    start_date: _date
    target_date: _date
    sex: Optional[str] = None
    previous_plan_id: Optional[str] = None
    status: str = "active"
    vlcd_acknowledged: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class WeightEntry:
    id: Optional[str]
    user_id: str
    log_date: _date
    weight_kg: float
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass
class FoodEntry:
    id: Optional[str]
    user_id: str
    log_date: _date
    name: str
    kcal: float
    log_time: Optional[str] = None
    portion_g: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    fibre_g: Optional[float] = None
    sugar_g: Optional[float] = None
    barcode: Optional[str] = None
    source: str = "manual"
    created_at: Optional[datetime] = None


@dataclass
class ExerciseEntry:
    id: Optional[str]
    user_id: str
    log_date: _date
    activity: str
    intensity: str
    duration_min: int
    kcal_burned: Optional[float] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass
class EarnedBadge:
    id: Optional[str]
    user_id: str
    badge_key: str
    earned_on: _date
    points: int = 0
    metadata: Optional[dict] = None
    created_at: Optional[datetime] = None


@dataclass
class ProviderConnection:
    id: Optional[str]
    user_id: str
    provider: str
    status: str
    credentials_encrypted: str
    external_connection_id: str
    display_name: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    last_error: Optional[str] = None


@dataclass
class AccountMapping:
    id: Optional[str]
    user_id: str
    provider_connection_id: str
    external_account_id: str
    external_account_name: str
    account_id: str


@dataclass
class SyncRun:
    id: Optional[str]
    user_id: str
    trigger: str
    as_of_date: _date
    status: str = "running"
    written_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    notes: Optional[str] = None
    undone_at: Optional[datetime] = None


@dataclass
class SyncRunItem:
    id: Optional[str]
    sync_run_id: str
    provider: str
    outcome: str
    account_id: Optional[str] = None
    external_account_id: Optional[str] = None
    reason: Optional[str] = None
    external_amount: Optional[float] = None
    external_currency: Optional[str] = None
    previous_value_gbp: Optional[float] = None
    new_value_gbp: Optional[float] = None
    had_previous: bool = False