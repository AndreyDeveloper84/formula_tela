"""Ayla nutrition backend — in-memory stateful mock for Phase 3 development.

Reference spec: docs/plans/maxbot-phase3-ayla-spec.md

Реализует contract из spec'а для разработки MAX-бота параллельно с
backend-командой Ayla. Покрывает все endpoints Phase 3.1/3.2/3.3:

    Profile:    GET/POST /api/v1/nutrition/internal/profile/
    Water:      POST/GET /api/v1/nutrition/internal/water/[today/|{id}/|{id}/restore/]
    Beverages:  GET /api/v1/nutrition/internal/beverages/
    Scan:       POST /api/v1/nutrition/internal/scan/  (с caption)
    Food log:   POST /api/v1/nutrition/internal/food-log/
    Summary:    GET /api/v1/nutrition/internal/summary/  (с with_comment)
    Deficits:   GET /api/v1/nutrition/internal/deficits/
    Patterns:   GET /api/v1/nutrition/internal/patterns/
    Insights:   GET /api/v1/nutrition/internal/insights/returning_success/

Usage in tests:

    from tests.fixtures.ayla_mock import AylaMockState, install_mock_transport

    @pytest.fixture
    def ayla(monkeypatch):
        state = AylaMockState()
        install_mock_transport(monkeypatch, state)
        return state

    async def test_anketa_full_flow(ayla):
        ayla.queue_scan_response(dish_name="Борщ", confidence=0.92, ...)
        # ... call bot handlers — they hit ayla via NutritionClient ...
        assert ayla.profiles["bot:1"].goal == "lose"
        assert ayla.water_entries[entry_id].water_ml == 188

Business logic implemented locally (NOT delegated to Ayla):
    - BMR (Mifflin-St Jeor)
    - Daily norm calc with goal-factor + activity coefficient
    - Goal override ladder (pregnancy/breastfeeding/eating_disorder/BMR floor)
    - Beverage water_coefficient + caffeine + kcal application
    - Milestone idempotency per-day per-threshold
    - Caffeine warning at 200mg/day for pregnant
    - Restore window 15 minutes after soft-delete

Scan/recognize uses queued responses — tests must call `queue_scan_response()`
before triggering bot photo handler.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

import httpx

logger = logging.getLogger("tests.ayla_mock")


# ─── Beverages catalog (seed) ──────────────────────────────────────────────
#
# Coefficients sourced from Beverage Hydration Index (Maughan et al. 2016,
# Am J Clin Nutr). Calorie/protein/fat/carb/caffeine values from USDA
# FoodData Central + Роспотребнадзор «Химический состав российских пищевых
# продуктов» (Скурихин-Тутельян).
#
# 25+ напитков покрывающих все категории. Можно расширить через
# state.add_beverage(slug=..., ...) в тестах.

BEVERAGES_SEED: list[dict[str, Any]] = [
    # ─── Water ───
    {
        "slug": "voda",
        "name_ru": "Вода",
        "category": "water",
        "aliases": ["вода", "water", "h2o"],
        "water_coefficient": 1.00,
        "kcal_per_100ml": 0,
        "default_serving_ml": 250,
        "default_serving_label": "стакан",
    },
    {
        "slug": "voda_mineralnaya",
        "name_ru": "Минеральная вода",
        "category": "water",
        "aliases": ["минеральная вода", "минералка", "боржоми", "ессентуки"],
        "water_coefficient": 1.00,
        "kcal_per_100ml": 0,
        "default_serving_ml": 250,
        "default_serving_label": "стакан",
    },
    # ─── Tea ───
    {
        "slug": "chai_chernyi",
        "name_ru": "Чёрный чай",
        "category": "tea",
        "aliases": ["чай", "чёрный чай", "черный чай", "tea"],
        "water_coefficient": 1.00,
        "kcal_per_100ml": 1,
        "caffeine_mg_per_100ml": 20,
        "default_serving_ml": 250,
        "default_serving_label": "кружка",
    },
    {
        "slug": "chai_zelenyi",
        "name_ru": "Зелёный чай",
        "category": "tea",
        "aliases": ["зелёный чай", "зеленый чай", "green tea"],
        "water_coefficient": 1.00,
        "kcal_per_100ml": 1,
        "caffeine_mg_per_100ml": 12,
        "default_serving_ml": 250,
        "default_serving_label": "кружка",
    },
    {
        "slug": "chai_travyanoi",
        "name_ru": "Травяной чай",
        "category": "tea",
        "aliases": ["травяной чай", "ромашка", "мята", "иван-чай"],
        "water_coefficient": 1.00,
        "kcal_per_100ml": 1,
        "caffeine_mg_per_100ml": 0,
        "default_serving_ml": 250,
        "default_serving_label": "кружка",
    },
    # ─── Coffee ───
    {
        "slug": "kofe_chernyi",
        "name_ru": "Чёрный кофе",
        "category": "coffee",
        "aliases": ["кофе", "coffee", "американо", "americano"],
        "water_coefficient": 1.00,
        "kcal_per_100ml": 2,
        "caffeine_mg_per_100ml": 40,
        "default_serving_ml": 200,
        "default_serving_label": "чашка",
    },
    {
        "slug": "kofe_espresso",
        "name_ru": "Эспрессо",
        "category": "coffee",
        "aliases": ["эспрессо", "espresso"],
        "water_coefficient": 1.00,
        "kcal_per_100ml": 5,
        "caffeine_mg_per_100ml": 200,
        "default_serving_ml": 30,
        "default_serving_label": "порция",
    },
    {
        "slug": "kofe_kapuchino",
        "name_ru": "Капучино",
        "category": "coffee",
        "aliases": ["капучино", "cappuccino"],
        "water_coefficient": 1.00,
        "kcal_per_100ml": 50,
        "protein_per_100ml": 2.5,
        "fat_per_100ml": 2.0,
        "carbs_per_100ml": 4.0,
        "caffeine_mg_per_100ml": 35,
        "default_serving_ml": 250,
        "default_serving_label": "чашка",
    },
    {
        "slug": "kofe_latte",
        "name_ru": "Латте",
        "category": "coffee",
        "aliases": ["латте", "latte"],
        "water_coefficient": 1.00,
        "kcal_per_100ml": 60,
        "protein_per_100ml": 3.0,
        "fat_per_100ml": 2.5,
        "carbs_per_100ml": 5.0,
        "caffeine_mg_per_100ml": 30,
        "default_serving_ml": 350,
        "default_serving_label": "стакан",
    },
    # ─── Juice ───
    {
        "slug": "sok_apelsinovyi",
        "name_ru": "Апельсиновый сок",
        "category": "juice",
        "aliases": ["апельсиновый сок", "сок апельсиновый", "oj"],
        "water_coefficient": 0.85,
        "kcal_per_100ml": 45,
        "protein_per_100ml": 0.7,
        "carbs_per_100ml": 10.0,
        "sugar_per_100ml": 8.0,
        "default_serving_ml": 200,
        "default_serving_label": "стакан",
    },
    {
        "slug": "sok_yablochnyi",
        "name_ru": "Яблочный сок",
        "category": "juice",
        "aliases": ["яблочный сок", "сок яблочный"],
        "water_coefficient": 0.85,
        "kcal_per_100ml": 46,
        "carbs_per_100ml": 11.0,
        "sugar_per_100ml": 9.5,
        "default_serving_ml": 200,
        "default_serving_label": "стакан",
    },
    {
        "slug": "sok_tomatnyi",
        "name_ru": "Томатный сок",
        "category": "juice",
        "aliases": ["томатный сок", "сок томатный"],
        "water_coefficient": 0.85,
        "kcal_per_100ml": 17,
        "protein_per_100ml": 0.8,
        "carbs_per_100ml": 3.0,
        "default_serving_ml": 200,
        "default_serving_label": "стакан",
    },
    # ─── Soda / sweet drinks ───
    {
        "slug": "kola",
        "name_ru": "Кола",
        "category": "soda",
        "aliases": ["кола", "coca-cola", "пепси", "pepsi"],
        "water_coefficient": 0.80,
        "kcal_per_100ml": 42,
        "carbs_per_100ml": 10.6,
        "sugar_per_100ml": 10.6,
        "caffeine_mg_per_100ml": 10,
        "default_serving_ml": 330,
        "default_serving_label": "банка",
    },
    {
        "slug": "limonad",
        "name_ru": "Лимонад",
        "category": "soda",
        "aliases": ["лимонад", "спрайт", "sprite", "fanta", "фанта"],
        "water_coefficient": 0.80,
        "kcal_per_100ml": 38,
        "carbs_per_100ml": 9.0,
        "sugar_per_100ml": 9.0,
        "default_serving_ml": 330,
        "default_serving_label": "банка",
    },
    # ─── Milk ───
    {
        "slug": "moloko",
        "name_ru": "Молоко",
        "category": "milk",
        "aliases": ["молоко", "milk", "молочко"],
        "water_coefficient": 1.50,
        "kcal_per_100ml": 60,
        "protein_per_100ml": 3.2,
        "fat_per_100ml": 2.5,
        "carbs_per_100ml": 4.7,
        "default_serving_ml": 250,
        "default_serving_label": "стакан",
    },
    {
        "slug": "kefir",
        "name_ru": "Кефир",
        "category": "milk",
        "aliases": ["кефир"],
        "water_coefficient": 1.50,
        "kcal_per_100ml": 53,
        "protein_per_100ml": 2.9,
        "fat_per_100ml": 2.5,
        "carbs_per_100ml": 4.0,
        "default_serving_ml": 250,
        "default_serving_label": "стакан",
    },
    {
        "slug": "ryazhenka",
        "name_ru": "Ряженка",
        "category": "milk",
        "aliases": ["ряженка"],
        "water_coefficient": 1.50,
        "kcal_per_100ml": 58,
        "protein_per_100ml": 2.8,
        "fat_per_100ml": 2.5,
        "carbs_per_100ml": 4.0,
        "default_serving_ml": 250,
        "default_serving_label": "стакан",
    },
    # ─── Alcohol ───
    {
        "slug": "pivo",
        "name_ru": "Пиво",
        "category": "alcohol",
        "aliases": ["пиво", "beer"],
        "water_coefficient": 0.70,
        "kcal_per_100ml": 43,
        "carbs_per_100ml": 3.6,
        "default_serving_ml": 500,
        "default_serving_label": "бокал",
    },
    {
        "slug": "vino_krasnoe",
        "name_ru": "Красное вино",
        "category": "alcohol",
        "aliases": ["красное вино", "вино", "wine", "red wine"],
        "water_coefficient": 0.40,
        "kcal_per_100ml": 85,
        "carbs_per_100ml": 2.6,
        "default_serving_ml": 150,
        "default_serving_label": "бокал",
    },
    {
        "slug": "vino_beloe",
        "name_ru": "Белое вино",
        "category": "alcohol",
        "aliases": ["белое вино", "white wine"],
        "water_coefficient": 0.40,
        "kcal_per_100ml": 82,
        "carbs_per_100ml": 2.6,
        "default_serving_ml": 150,
        "default_serving_label": "бокал",
    },
    {
        "slug": "vodka",
        "name_ru": "Водка",
        "category": "alcohol",
        "aliases": ["водка", "vodka"],
        "water_coefficient": -0.50,
        "kcal_per_100ml": 235,
        "default_serving_ml": 50,
        "default_serving_label": "рюмка",
    },
    {
        "slug": "konyak",
        "name_ru": "Коньяк",
        "category": "alcohol",
        "aliases": ["коньяк", "cognac"],
        "water_coefficient": -0.50,
        "kcal_per_100ml": 240,
        "default_serving_ml": 50,
        "default_serving_label": "рюмка",
    },
    # ─── Broth ───
    {
        "slug": "bulyon",
        "name_ru": "Бульон",
        "category": "broth",
        "aliases": ["бульон", "куриный бульон", "broth"],
        "water_coefficient": 0.90,
        "kcal_per_100ml": 15,
        "protein_per_100ml": 1.5,
        "fat_per_100ml": 0.5,
        "default_serving_ml": 250,
        "default_serving_label": "тарелка",
    },
    # ─── Sport drinks ───
    {
        "slug": "izotonik",
        "name_ru": "Изотонический напиток",
        "category": "sport",
        "aliases": ["изотоник", "powerade", "gatorade", "спорт-напиток"],
        "water_coefficient": 0.95,
        "kcal_per_100ml": 25,
        "carbs_per_100ml": 6.0,
        "sugar_per_100ml": 5.5,
        "default_serving_ml": 500,
        "default_serving_label": "бутылка",
    },
]


# ─── Constants — business logic ────────────────────────────────────────────

GOAL_FACTORS: dict[tuple[str, str | None], float] = {
    ("lose", "gentle"): 0.90,
    ("lose", "moderate"): 0.85,
    ("lose", "fast"): 0.80,
    ("lose", None): 0.85,  # default if pace unset
    ("maintain", None): 1.00,
    ("maintain", "gentle"): 1.00,
    ("maintain", "moderate"): 1.00,
    ("gain", None): 1.10,
    ("gain", "gentle"): 1.05,
    ("gain", "moderate"): 1.10,
    ("gain", "fast"): 1.15,
    ("tone", None): 1.00,
    ("tone", "gentle"): 1.00,
    ("tone", "moderate"): 1.00,
}

DEFAULT_ACTIVITY_COEFFICIENT = 1.4
BMR_FLOOR_BUFFER_KCAL = 100  # daily_kcal must be >= bmr + 100
WATER_NORM_ML_PER_KG = 30
DEFAULT_WATER_NORM_ML = 2000
PREGNANT_CAFFEINE_LIMIT_MG = 200
RESTORE_WINDOW_S = 15 * 60  # 15 minutes

# Defaults для пропущенных полей анкеты (медиана аудитории Пензы 35-45 ж).
DEFAULT_GENDER = "female"
DEFAULT_AGE = 40
DEFAULT_HEIGHT_CM = 165
DEFAULT_WEIGHT_KG = 70.0


# ─── State containers ──────────────────────────────────────────────────────

@dataclass
class MockProfile:
    external_user_id: str
    gender: str | None = None
    age: int | None = None
    height_cm: int | None = None
    weight_kg: float | None = None
    weight_range: str | None = None
    activity_coefficient: float = DEFAULT_ACTIVITY_COEFFICIENT
    goal: str | None = None
    pace: str | None = None
    diet_preference: str = "none"
    health_flags: dict[str, Any] = field(default_factory=dict)
    disclaimer_acked: dict[str, Any] | None = None
    onboarded_at: str | None = None
    first_food_logged_at: str | None = None
    weekly_summary_unlocked_at: str | None = None
    goal_overridden_by: str | None = None
    bmi_warning_overridden_at: str | None = None
    overrides_applied: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: _utc_now_iso())
    updated_at: str = field(default_factory=lambda: _utc_now_iso())

    # Computed (refreshed on every upsert)
    bmr: int | None = None
    daily_kcal: int | None = None
    daily_protein_g: int | None = None
    daily_fat_g: int | None = None
    daily_carbs_g: int | None = None
    daily_water_ml: int | None = None


@dataclass
class MockWaterEntry:
    entry_id: str
    external_user_id: str
    ts: datetime
    ml: int
    water_ml: int
    beverage_slug: str | None
    beverage_name: str | None
    beverage_label: str | None
    kcal: int
    protein_g: float
    fat_g: float
    carbs_g: float
    caffeine_mg: int
    deleted_at: datetime | None = None
    deleted_reason: str | None = None


@dataclass
class MockFoodEntry:
    entry_id: str
    external_user_id: str
    ts: datetime
    name: str
    kcal: int
    protein_g: float
    fat_g: float
    carbs_g: float
    meal_type: str
    scan_id: str | None = None
    deleted_at: datetime | None = None


@dataclass
class QueuedScanResponse:
    """Test setup: response для следующего scan_photo вызова."""
    dish_name: str
    confidence: float
    portion_g: int | None = 250
    nutrition: dict[str, Any] = field(default_factory=lambda: {
        "calories": 300, "protein_g": 15.0, "fat_g": 10.0, "carbs_g": 30.0,
    })
    is_food: bool = True
    error_code: str | None = None  # set "FOOD_NOT_RECOGNIZED" чтобы вернуть 400


# ─── Mock state ────────────────────────────────────────────────────────────

class AylaMockState:
    """In-memory stateful Ayla backend simulator."""

    def __init__(self) -> None:
        self.profiles: dict[str, MockProfile] = {}
        self.water_entries: dict[str, MockWaterEntry] = {}
        self.food_entries: dict[str, MockFoodEntry] = {}
        self.beverages: dict[str, dict[str, Any]] = {
            b["slug"]: b for b in BEVERAGES_SEED
        }
        # Per-user, per-day milestone tracker — to ensure idempotency
        # of milestone_text in /water/ POST responses.
        # Format: {(external_user_id, date_iso): set_of_thresholds_shown}
        self._milestones_shown: dict[tuple[str, str], set[int]] = defaultdict(set)
        # Test-side scan response queue
        self._scan_queue: list[QueuedScanResponse] = []
        # Idempotency-Key cache for replay support
        self._idem_cache: dict[str, dict[str, Any]] = {}
        # Test instrumentation — list of all requests received
        self.requests_log: list[dict[str, Any]] = []

    # ─── Test helpers ──────────────────────────────────────────────────

    def queue_scan_response(self, **kwargs: Any) -> None:
        """Test setup: enqueue next scan response.

        If queue empty during scan call, returns generic dish_name="Блюдо".
        """
        self._scan_queue.append(QueuedScanResponse(**kwargs))

    def add_beverage(self, **kwargs: Any) -> None:
        """Test setup: extend beverages catalog."""
        self.beverages[kwargs["slug"]] = kwargs

    def reset(self) -> None:
        self.profiles.clear()
        self.water_entries.clear()
        self.food_entries.clear()
        self._milestones_shown.clear()
        self._scan_queue.clear()
        self._idem_cache.clear()
        self.requests_log.clear()

    # ─── Business logic — used by handlers below ──────────────────────

    def _calc_norms(self, profile: MockProfile) -> None:
        """Compute BMR + daily_* on profile in-place. Apply override ladder."""
        profile.overrides_applied = []
        profile.goal_overridden_by = None

        # Effective field values — substitute defaults for skipped/missing.
        gender = profile.gender or DEFAULT_GENDER
        age = profile.age or DEFAULT_AGE
        height = profile.height_cm or DEFAULT_HEIGHT_CM
        weight = profile.weight_kg or DEFAULT_WEIGHT_KG

        # Mifflin-St Jeor.
        bmr = 10 * weight + 6.25 * height - 5 * age
        bmr += -161 if gender == "female" else 5
        profile.bmr = int(round(bmr))

        # Goal override ladder.
        flags = profile.health_flags
        original_goal = profile.goal
        original_pace = profile.pace
        effective_goal = profile.goal or "maintain"
        effective_pace = profile.pace

        # 1. eating_disorder → maintain (highest priority).
        if flags.get("eating_disorder"):
            if effective_goal != "maintain":
                profile.overrides_applied.append({
                    "reason": "eating_disorder",
                    "from": {"goal": effective_goal},
                    "to": {"goal": "maintain"},
                })
                effective_goal = "maintain"
                effective_pace = None
                profile.goal_overridden_by = "eating_disorder"

        # 2. pregnancy / breastfeeding → maintain.
        elif flags.get("pregnant") or flags.get("breastfeeding"):
            if effective_goal == "lose":
                reason = "pregnancy" if flags.get("pregnant") else "breastfeeding"
                profile.overrides_applied.append({
                    "reason": reason,
                    "from": {"goal": "lose"},
                    "to": {"goal": "maintain"},
                })
                effective_goal = "maintain"
                effective_pace = None
                profile.goal_overridden_by = reason

        # Compute daily_kcal.
        factor = GOAL_FACTORS.get((effective_goal, effective_pace))
        if factor is None:
            factor = GOAL_FACTORS.get((effective_goal, None), 1.0)
        daily_kcal = int(round(profile.bmr * profile.activity_coefficient * factor))

        # 3. BMR floor ladder — only if still in deficit.
        if effective_goal == "lose":
            floor = profile.bmr + BMR_FLOOR_BUFFER_KCAL
            if daily_kcal < floor:
                if effective_pace == "moderate":
                    # Try gentle.
                    profile.overrides_applied.append({
                        "reason": "bmr_floor",
                        "from": {"pace": "moderate"},
                        "to": {"pace": "gentle"},
                    })
                    effective_pace = "gentle"
                    factor = GOAL_FACTORS[("lose", "gentle")]
                    daily_kcal = int(round(profile.bmr * profile.activity_coefficient * factor))
                if daily_kcal < floor:
                    # Still below — switch to maintain.
                    profile.overrides_applied.append({
                        "reason": "bmr_floor",
                        "from": {"goal": "lose"},
                        "to": {"goal": "maintain"},
                    })
                    effective_goal = "maintain"
                    effective_pace = None
                    factor = 1.0
                    daily_kcal = int(round(profile.bmr * profile.activity_coefficient))
                    profile.goal_overridden_by = "bmr_floor"

        profile.daily_kcal = daily_kcal

        # Macro split (g/kg of bodyweight, standard nutrition guidelines).
        protein_per_kg = 1.6 if effective_goal in ("lose", "tone") else 1.2
        if flags.get("pregnant") or flags.get("breastfeeding"):
            protein_per_kg = max(protein_per_kg, 1.4)  # +25g approx.
        profile.daily_protein_g = int(round(weight * protein_per_kg))
        profile.daily_fat_g = int(round(daily_kcal * 0.30 / 9))
        profile.daily_carbs_g = int(round(
            (daily_kcal - profile.daily_protein_g * 4 - profile.daily_fat_g * 9) / 4
        ))

        # Water norm — 30 ml/kg.
        profile.daily_water_ml = int(round(weight * WATER_NORM_ML_PER_KG))

        # +400 kcal ГВ, +200 беременность (post-trimester not modeled — flat add).
        if flags.get("breastfeeding"):
            profile.daily_kcal += 400
            profile.daily_protein_g += 25
        elif flags.get("pregnant"):
            profile.daily_kcal += 200
            profile.daily_protein_g += 25

    def upsert_profile(
        self,
        external_user_id: str,
        patch: dict[str, Any],
    ) -> MockProfile:
        """Implements POST /profile/ business logic."""
        prof = self.profiles.get(external_user_id) or MockProfile(
            external_user_id=external_user_id,
        )
        for key in (
            "gender", "age", "height_cm", "weight_kg", "weight_range",
            "activity_coefficient", "goal", "pace", "diet_preference",
            "disclaimer_acked",
        ):
            if key in patch and patch[key] is not None:
                setattr(prof, key, patch[key])
        if "health_flags" in patch and isinstance(patch["health_flags"], dict):
            prof.health_flags.update(patch["health_flags"])
        if "_skipped_fields" in patch:
            for f in patch["_skipped_fields"]:
                prof.health_flags[f"{f}_skipped"] = True
        if patch.get("complete") and not prof.onboarded_at:
            prof.onboarded_at = _utc_now_iso()

        self._calc_norms(prof)
        prof.updated_at = _utc_now_iso()
        self.profiles[external_user_id] = prof
        return prof

    def _resolve_beverage(self, slug: str | None) -> dict[str, Any] | None:
        if slug is None:
            return None
        return self.beverages.get(slug)

    def add_water(
        self,
        external_user_id: str,
        ml: int,
        beverage_slug: str | None = None,
        ts: datetime | None = None,
    ) -> dict[str, Any]:
        """Implements POST /water/ business logic.

        Returns response dict ready to be JSON-serialized.
        """
        ts = ts or _utc_now()
        bev = self._resolve_beverage(beverage_slug)
        coef = float(bev["water_coefficient"]) if bev else 1.0
        water_ml = int(round(ml * coef))
        kcal = 0
        protein_g = 0.0
        fat_g = 0.0
        carbs_g = 0.0
        caffeine_mg = 0
        if bev:
            kcal = int(round(ml * (bev.get("kcal_per_100ml") or 0) / 100))
            protein_g = float(ml * (bev.get("protein_per_100ml") or 0) / 100)
            fat_g = float(ml * (bev.get("fat_per_100ml") or 0) / 100)
            carbs_g = float(ml * (bev.get("carbs_per_100ml") or 0) / 100)
            caffeine_mg = int(round(ml * (bev.get("caffeine_mg_per_100ml") or 0) / 100))

        entry_id = str(uuid.uuid4())
        entry = MockWaterEntry(
            entry_id=entry_id,
            external_user_id=external_user_id,
            ts=ts,
            ml=ml,
            water_ml=water_ml,
            beverage_slug=beverage_slug,
            beverage_name=bev["name_ru"] if bev else None,
            beverage_label=bev["default_serving_label"] if bev else None,
            kcal=kcal,
            protein_g=protein_g,
            fat_g=fat_g,
            carbs_g=carbs_g,
            caffeine_mg=caffeine_mg,
        )
        self.water_entries[entry_id] = entry

        # Eating disorder mode — strip cal/milestone.
        prof = self.profiles.get(external_user_id)
        ed_mode = bool(prof and prof.health_flags.get("eating_disorder"))

        # Today aggregates.
        today_total = self._today_water_ml(external_user_id, ts.date())
        norm = (prof and prof.daily_water_ml) or DEFAULT_WATER_NORM_ML
        progress_pct = int(round(today_total / norm * 100)) if norm else 0

        # Milestone idempotency.
        milestone_text = None
        if not ed_mode:
            key = (external_user_id, ts.date().isoformat())
            shown = self._milestones_shown[key]
            for threshold, text in [
                (50, "половина дня 💪"),
                (100, "норма! 👍"),
                (150, "Хорошо пьёшь! Если не хочется — на сегодня хватит."),
            ]:
                if progress_pct >= threshold and threshold not in shown:
                    milestone_text = text
                    shown.add(threshold)
                    break

        alcohol_recovery_hint = (
            not ed_mode and bev is not None and bev["category"] == "alcohol"
        )

        caffeine_warning = None
        if not ed_mode and prof and prof.health_flags.get("pregnant"):
            today_caffeine = self._today_caffeine_mg(external_user_id, ts.date())
            if today_caffeine >= PREGNANT_CAFFEINE_LIMIT_MG:
                caffeine_warning = "пограничное значение для беременности"

        return {
            "entry_id": entry_id,
            "ml": ml,
            "water_ml": water_ml,
            "beverage_name": entry.beverage_name,
            "beverage_label": entry.beverage_label,
            "kcal": 0 if ed_mode else kcal,
            "protein_g": 0.0 if ed_mode else round(protein_g, 1),
            "fat_g": 0.0 if ed_mode else round(fat_g, 1),
            "carbs_g": 0.0 if ed_mode else round(carbs_g, 1),
            "caffeine_mg": 0 if ed_mode else caffeine_mg,
            "today_total_water_ml": today_total,
            "today_norm_water_ml": norm,
            "today_progress_pct": progress_pct,
            "milestone_text": milestone_text,
            "alcohol_recovery_hint": alcohol_recovery_hint,
            "caffeine_warning": caffeine_warning,
            "ts": ts.isoformat(),
        }

    def soft_delete_water(self, entry_id: str) -> dict[str, Any] | None:
        entry = self.water_entries.get(entry_id)
        if entry is None or entry.deleted_at is not None:
            return None
        entry.deleted_at = _utc_now()
        entry.deleted_reason = "user_undo"
        return {
            "entry_id": entry_id,
            "deleted": True,
            "today_total_water_ml": self._today_water_ml(
                entry.external_user_id, entry.ts.date(),
            ),
            "restore_window_expires_at": (
                entry.deleted_at + timedelta(seconds=RESTORE_WINDOW_S)
            ).isoformat(),
        }

    def restore_water(self, entry_id: str) -> dict[str, Any] | None:
        entry = self.water_entries.get(entry_id)
        if entry is None or entry.deleted_at is None:
            return None
        if (_utc_now() - entry.deleted_at).total_seconds() > RESTORE_WINDOW_S:
            return {"_expired": True}
        entry.deleted_at = None
        entry.deleted_reason = None
        return {
            "entry_id": entry_id,
            "restored": True,
            "today_total_water_ml": self._today_water_ml(
                entry.external_user_id, entry.ts.date(),
            ),
        }

    def _today_water_ml(self, ext: str, day: date) -> int:
        return sum(
            e.water_ml
            for e in self.water_entries.values()
            if e.external_user_id == ext
            and e.ts.date() == day
            and e.deleted_at is None
        )

    def _today_caffeine_mg(self, ext: str, day: date) -> int:
        return sum(
            e.caffeine_mg
            for e in self.water_entries.values()
            if e.external_user_id == ext
            and e.ts.date() == day
            and e.deleted_at is None
        )

    def water_today_payload(self, external_user_id: str) -> dict[str, Any]:
        today = _utc_now().date()
        entries = [
            e for e in self.water_entries.values()
            if e.external_user_id == external_user_id and e.ts.date() == today
        ]
        prof = self.profiles.get(external_user_id)
        norm = (prof and prof.daily_water_ml) or DEFAULT_WATER_NORM_ML

        coffee_cups = sum(
            1 for e in entries
            if e.deleted_at is None and e.beverage_slug
            and self.beverages.get(e.beverage_slug, {}).get("category") == "coffee"
        )
        tea_cups = sum(
            1 for e in entries
            if e.deleted_at is None and e.beverage_slug
            and self.beverages.get(e.beverage_slug, {}).get("category") == "tea"
        )

        return {
            "date": today.isoformat(),
            "entries": [
                {
                    "entry_id": e.entry_id,
                    "ts": e.ts.isoformat(),
                    "ml": e.ml,
                    "water_ml": e.water_ml,
                    "beverage_slug": e.beverage_slug,
                    "beverage_name": e.beverage_name,
                    "deleted": e.deleted_at is not None,
                }
                for e in sorted(entries, key=lambda e: e.ts)
            ],
            "today_total_water_ml": self._today_water_ml(external_user_id, today),
            "today_norm_water_ml": norm,
            "today_kcal_from_beverages": sum(
                e.kcal for e in entries if e.deleted_at is None
            ),
            "today_caffeine_mg": self._today_caffeine_mg(external_user_id, today),
            "today_total_coffee_cups": coffee_cups,
            "today_total_tea_cups": tea_cups,
        }

    def beverages_payload(self) -> dict[str, Any]:
        return {
            "beverages": [
                {
                    "slug": b["slug"],
                    "name_ru": b["name_ru"],
                    "category": b["category"],
                    "aliases": b.get("aliases", []),
                    "default_serving_ml": b["default_serving_ml"],
                    "default_serving_label": b["default_serving_label"],
                }
                for b in self.beverages.values()
            ],
        }

    def consume_scan(self, caption: str | None = None) -> QueuedScanResponse:
        if self._scan_queue:
            return self._scan_queue.pop(0)
        return QueuedScanResponse(
            dish_name="Блюдо",
            confidence=0.85,
            portion_g=250,
            nutrition={
                "calories": 300, "protein_g": 15.0, "fat_g": 10.0, "carbs_g": 30.0,
            },
        )

    def daily_summary_payload(
        self,
        external_user_id: str,
        date_iso: str | None = None,
        with_comment: bool = False,
    ) -> dict[str, Any]:
        prof = self.profiles.get(external_user_id)
        target_date = (
            datetime.fromisoformat(date_iso).date() if date_iso
            else _utc_now().date()
        )
        entries = [
            e for e in self.food_entries.values()
            if e.external_user_id == external_user_id
            and e.ts.date() == target_date
            and e.deleted_at is None
        ]
        cal_total = sum(e.kcal for e in entries)
        protein = sum(e.protein_g for e in entries)
        fat = sum(e.fat_g for e in entries)
        carbs = sum(e.carbs_g for e in entries)

        payload: dict[str, Any] = {
            "date": target_date.isoformat(),
            "calories_total": float(cal_total),
            "calories_goal": (prof and prof.daily_kcal) or 2000,
            "protein_g": round(protein, 1),
            "fat_g": round(fat, 1),
            "carbs_g": round(carbs, 1),
            "entries": [
                {
                    "id": e.entry_id,
                    "name": e.name,
                    "meal_type": e.meal_type,
                    "calories": e.kcal,
                    "protein_g": round(e.protein_g, 1),
                    "fat_g": round(e.fat_g, 1),
                    "carbs_g": round(e.carbs_g, 1),
                    "ts": e.ts.isoformat(),
                }
                for e in sorted(entries, key=lambda e: e.ts)
            ],
        }
        if with_comment:
            payload["ai_comment"] = self._mock_comment(prof, payload)
        return payload

    def _mock_comment(
        self, prof: MockProfile | None, payload: dict[str, Any],
    ) -> str:
        """Stub AI-generated comment for /summary/?with_comment=true."""
        if prof and prof.health_flags.get("eating_disorder"):
            return "Как ты сегодня? День получился?"
        cal_total = payload["calories_total"]
        cal_goal = payload["calories_goal"] or 1
        pct = int(cal_total / cal_goal * 100)
        if pct >= 95:
            return "Хороший день — почти в норму. Завтра попробуй больше белка утром."
        if pct < 50:
            return "В дневнике сегодня немного. Если что-то ещё ела — добавь, посчитаю."
        return "Стабильно идёшь. Завтра можно чуть прибавить белка."

    def deficits_payload(self, external_user_id: str, days: int = 7) -> dict[str, Any]:
        return {
            "days_observed": min(days, 7),
            "protein_avg_pct_goal": 75.0,
            "protein_low_streak_days": 3,
            "hint": "",
            "fired_keys": [],
        }

    def patterns_payload(self, external_user_id: str) -> dict[str, Any]:
        # Phase 3.3 stub. Tests can populate via state hooks if needed.
        return {"active_days": 0, "patterns": []}

    def returning_success_payload(self, external_user_id: str) -> dict[str, Any]:
        return {"detected": False}


# ─── HTTP transport — translates http calls to state methods ──────────────

class _AylaMockTransport(httpx.MockTransport):
    """httpx transport that routes Phase 3 endpoints to AylaMockState."""

    def __init__(self, state: AylaMockState) -> None:
        self.state = state
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        ext = request.headers.get("X-External-User-ID", "")
        token = request.headers.get("X-Service-Token", "")

        # Audit log for tests.
        self.state.requests_log.append({
            "method": method,
            "path": path,
            "ext": ext,
            "query": dict(request.url.params),
        })

        # Auth check.
        if not token:
            return _err(401, "MISSING_SERVICE_TOKEN")
        if not ext.startswith("bot:"):
            return _err(401, "MISSING_EXTERNAL_USER_ID")

        try:
            return self._route(method, path, ext, request)
        except Exception as exc:  # noqa: BLE001
            logger.exception("ayla_mock unhandled %s %s: %s", method, path, exc)
            return _err(500, "MOCK_ERROR", message=str(exc))

    def _route(
        self, method: str, path: str, ext: str, request: httpx.Request,
    ) -> httpx.Response:
        # Profile.
        if path == "/api/v1/nutrition/internal/profile/":
            if method == "GET":
                prof = self.state.profiles.get(ext)
                if prof is None:
                    return _ok({"external_user_id": ext, "exists": False})
                return _ok({"external_user_id": ext, "exists": True, **_profile_dict(prof)})
            if method == "POST":
                body = json.loads(request.content or b"{}")
                prof = self.state.upsert_profile(ext, body)
                return _ok(
                    {
                        "external_user_id": ext,
                        "exists": True,
                        **_profile_dict(prof),
                        "overrides_applied": prof.overrides_applied,
                    }
                )

        # Beverages.
        if path == "/api/v1/nutrition/internal/beverages/" and method == "GET":
            return _ok(self.state.beverages_payload())

        # Water root.
        if path == "/api/v1/nutrition/internal/water/":
            if method == "POST":
                body = json.loads(request.content or b"{}")
                ml = int(body.get("ml") or 0)
                if ml < 10 or ml > 3000:
                    return _err(400, "INVALID_ML")
                slug = body.get("beverage_slug")
                if slug and slug not in self.state.beverages:
                    return _err(400, "UNKNOWN_BEVERAGE")
                ts_raw = body.get("ts")
                ts = (
                    datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    if ts_raw else None
                )
                payload = self.state.add_water(ext, ml, slug, ts)
                return _ok(payload, status=201)
        if path == "/api/v1/nutrition/internal/water/today/" and method == "GET":
            return _ok(self.state.water_today_payload(ext))

        # Water entry-specific.
        if path.startswith("/api/v1/nutrition/internal/water/"):
            tail = path.removeprefix("/api/v1/nutrition/internal/water/").rstrip("/")
            parts = tail.split("/")
            if len(parts) == 1 and method == "DELETE":
                resp = self.state.soft_delete_water(parts[0])
                if resp is None:
                    return _err(404, "ENTRY_NOT_FOUND")
                return _ok(resp)
            if len(parts) == 2 and parts[1] == "restore" and method == "POST":
                resp = self.state.restore_water(parts[0])
                if resp is None:
                    return _err(404, "ENTRY_NOT_FOUND")
                if resp.get("_expired"):
                    return _err(410, "RESTORE_WINDOW_EXPIRED")
                return _ok(resp)

        # Scan (existing endpoint, extended with caption).
        if path == "/api/v1/nutrition/internal/scan/" and method == "POST":
            qs = self.state.consume_scan()
            if qs.error_code:
                return _err(400, qs.error_code)
            return _ok({
                "id": str(uuid.uuid4()),
                "dish_name": qs.dish_name,
                "confidence": qs.confidence,
                "portion_g": qs.portion_g,
                "nutrition": qs.nutrition,
                "provider": "mock",
                "is_food": qs.is_food,
            })

        # Food log.
        if path == "/api/v1/nutrition/internal/food-log/" and method == "POST":
            body = json.loads(request.content or b"{}")
            entry = MockFoodEntry(
                entry_id=str(uuid.uuid4()),
                external_user_id=ext,
                ts=_utc_now(),
                name=body.get("dish_name") or "Блюдо",
                meal_type=body.get("meal_type") or "snack",
                kcal=int(body.get("calories") or 300),
                protein_g=float(body.get("protein_g") or 15),
                fat_g=float(body.get("fat_g") or 10),
                carbs_g=float(body.get("carbs_g") or 30),
                scan_id=body.get("scan_id"),
            )
            self.state.food_entries[entry.entry_id] = entry
            return _ok({
                "id": entry.entry_id,
                "dish_name": entry.name,
                "meal_type": entry.meal_type,
                "calories": entry.kcal,
                "protein_g": entry.protein_g,
                "fat_g": entry.fat_g,
                "carbs_g": entry.carbs_g,
            }, status=201)

        # Summary.
        if path == "/api/v1/nutrition/internal/summary/" and method == "GET":
            params = dict(request.url.params)
            return _ok(self.state.daily_summary_payload(
                ext,
                date_iso=params.get("date"),
                with_comment=params.get("with_comment") == "true",
            ))

        # Deficits.
        if path == "/api/v1/nutrition/internal/deficits/" and method == "GET":
            days = int(request.url.params.get("days") or 7)
            return _ok(self.state.deficits_payload(ext, days))

        # Patterns (Phase 3.3).
        if path == "/api/v1/nutrition/internal/patterns/" and method == "GET":
            return _ok(self.state.patterns_payload(ext))

        # Returning success insight (Phase 3.3).
        if path == "/api/v1/nutrition/internal/insights/returning_success/" and method == "GET":
            return _ok(self.state.returning_success_payload(ext))

        return _err(404, "ROUTE_NOT_FOUND", message=f"{method} {path}")


# ─── Public API ────────────────────────────────────────────────────────────

def install_mock_transport(monkeypatch, state: AylaMockState) -> None:
    """Patch httpx.AsyncClient so all requests from NutritionClient hit AylaMockState.

    Pytest usage:
        @pytest.fixture
        def ayla(monkeypatch):
            state = AylaMockState()
            install_mock_transport(monkeypatch, state)
            return state
    """
    transport = _AylaMockTransport(state)
    original = httpx.AsyncClient

    class _PatchedAsyncClient(original):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _PatchedAsyncClient)
    # Also reset the NutritionClient singleton — it caches httpx.AsyncClient
    # construction logic per-call, but the singleton itself caches base_url+token
    # which is fine; resetting ensures clean circuit-breaker state per test.
    try:
        from maxbot.services.nutrition_client import reset_nutrition_client
        reset_nutrition_client()
        monkeypatch.setenv("AYLA_BASE_URL", "http://ayla.test")
        monkeypatch.setenv("NUTRITION_SERVICE_TOKEN", "test-token")
    except ImportError:
        # nutrition_client may not be importable in pure-fixture tests
        pass


# ─── Helpers ───────────────────────────────────────────────────────────────

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _ok(data: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"data": data})


def _err(status: int, code: str, *, message: str = "x") -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": message}})


def _profile_dict(prof: MockProfile) -> dict[str, Any]:
    """Serialize MockProfile → response dict matching /profile/ contract."""
    return {
        "gender": prof.gender,
        "age": prof.age,
        "height_cm": prof.height_cm,
        "weight_kg": float(prof.weight_kg) if prof.weight_kg is not None else None,
        "weight_range": prof.weight_range,
        "activity_coefficient": float(prof.activity_coefficient),
        "goal": prof.goal,
        "pace": prof.pace,
        "diet_preference": prof.diet_preference,
        "norms": {
            "bmr": prof.bmr,
            "daily_kcal": prof.daily_kcal,
            "daily_protein_g": prof.daily_protein_g,
            "daily_fat_g": prof.daily_fat_g,
            "daily_carbs_g": prof.daily_carbs_g,
            "daily_water_ml": prof.daily_water_ml,
        },
        "health_flags": prof.health_flags,
        "goal_overridden_by": prof.goal_overridden_by,
        "bmi_warning_overridden_at": prof.bmi_warning_overridden_at,
        "disclaimer_acked": prof.disclaimer_acked,
        "onboarded_at": prof.onboarded_at,
        "first_food_logged_at": prof.first_food_logged_at,
        "weekly_summary_unlocked_at": prof.weekly_summary_unlocked_at,
        "created_at": prof.created_at,
        "updated_at": prof.updated_at,
    }
