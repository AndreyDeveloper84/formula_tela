"""HTTP client for Ayla nutrition API (DRF-246).

Service-to-service calls from the MAX bot to Ayla. Authenticates via
`X-Service-Token` (shared secret) + `X-External-User-ID` (e.g. `bot:12345`).

Endpoints (all under `AYLA_BASE_URL`):
- POST /api/v1/nutrition/internal/scan/         — multipart photo
- POST /api/v1/nutrition/internal/food-log/     — DRF-247 (placeholder)
- GET  /api/v1/nutrition/internal/summary/      — DRF-247 (placeholder)
- GET  /api/v1/nutrition/internal/deficits/     — DRF-248 (placeholder)

Resilience:
- Per-call timeout (default 10s).
- Circuit breaker: 3 failures within 60s → 60s cool-down on subsequent calls.
- Caller-side retries are out of scope (MAX webhook fires once per photo).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from django.conf import settings


logger = logging.getLogger("maxbot.nutrition_client")

DEFAULT_TIMEOUT_S = 10.0
CIRCUIT_FAILURE_WINDOW_S = 60.0
CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_OPEN_DURATION_S = 60.0


@dataclass
class _Circuit:
    """Tiny in-process circuit breaker.

    Not thread-safe across worker processes, which is fine: each MAX bot
    worker tracks its own failures; if Ayla goes down, every worker will
    independently open its breaker within seconds. We don't need shared
    state to be useful.
    """

    failures: list[float] = field(default_factory=list)
    opened_at: float | None = None

    def is_open(self, *, now: float) -> bool:
        if self.opened_at is None:
            return False
        if now - self.opened_at >= CIRCUIT_OPEN_DURATION_S:
            self.opened_at = None
            self.failures = []
            return False
        return True

    def record_failure(self, *, now: float) -> None:
        cutoff = now - CIRCUIT_FAILURE_WINDOW_S
        self.failures = [t for t in self.failures if t >= cutoff]
        self.failures.append(now)
        if len(self.failures) >= CIRCUIT_FAILURE_THRESHOLD:
            self.opened_at = now
            logger.warning(
                "nutrition_client.circuit_opened failures=%d window_s=%.0f",
                len(self.failures), CIRCUIT_FAILURE_WINDOW_S,
            )

    def record_success(self) -> None:
        self.failures = []
        self.opened_at = None


class NutritionAPIError(Exception):
    """Base for client-visible failures."""


class NutritionUnavailableError(NutritionAPIError):
    """Ayla is down or the circuit is open — caller should show a fallback message."""


class FoodNotRecognizedError(NutritionAPIError):
    """Ayla returned 400 FOOD_NOT_RECOGNIZED — not food / unreadable photo."""


@dataclass(frozen=True)
class ScanResponse:
    """Subset of `FoodScanResponseSerializer` data we care about in the bot."""

    scan_id: str
    dish_name: str
    confidence: float
    portion_g: float | None
    nutrition: dict[str, Any] | None  # {calories, protein_g, fat_g, carbs_g, vitamins?}
    provider: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class FoodLogResponse:
    """Subset of `FoodLogEntrySerializer` data we care about in the bot."""

    log_id: str
    dish_name: str
    meal_type: str
    calories: float
    raw: dict[str, Any]


@dataclass(frozen=True)
class SummaryResponse:
    """Subset of `NutritionSummaryResponseSerializer` data we care about."""

    date: str
    calories_total: float
    calories_goal: int
    protein_g: float
    fat_g: float
    carbs_g: float
    entries: list[dict[str, Any]]
    raw: dict[str, Any]


@dataclass(frozen=True)
class DeficitsResponse:
    """Cross-domain bridge signal from /internal/deficits/ (DRF-248)."""

    days_observed: int
    protein_avg_pct_goal: float | None
    protein_low_streak_days: int
    hint: str  # may be empty — caller checks before passing to prompt
    fired_keys: list[str]
    raw: dict[str, Any]


class NutritionClient:
    """Async client. One instance shared by handlers; circuit state is per-instance.

    Construct via `get_nutrition_client()` — module-level singleton.
    """

    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        if not base_url:
            raise ValueError("AYLA_BASE_URL is empty — nutrition client cannot start")
        if not service_token:
            raise ValueError("NUTRITION_SERVICE_TOKEN is empty — nutrition client cannot start")
        self._base_url = base_url.rstrip("/")
        self._token = service_token
        self._timeout_s = timeout_s
        self._circuit = _Circuit()

    async def scan_photo(
        self,
        *,
        external_user_id: str,
        image_bytes: bytes,
        filename: str = "meal.jpg",
        portion_multiplier: float | None = None,
    ) -> ScanResponse:
        """POST /api/v1/nutrition/internal/scan/.

        Raises:
            NutritionUnavailableError: circuit open, network error, 5xx, timeout.
            FoodNotRecognizedError: 400 FOOD_NOT_RECOGNIZED.
            NutritionAPIError: other 4xx.
        """
        now = time.monotonic()
        if self._circuit.is_open(now=now):
            raise NutritionUnavailableError("circuit_open")

        url = f"{self._base_url}/api/v1/nutrition/internal/scan/"
        headers = {
            "X-Service-Token": self._token,
            "X-External-User-ID": external_user_id,
        }
        files = {"image": (filename, image_bytes, "image/jpeg")}
        data: dict[str, str] = {}
        if portion_multiplier is not None:
            data["portion_multiplier"] = str(portion_multiplier)

        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as http:
                resp = await http.post(url, headers=headers, files=files, data=data)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            self._circuit.record_failure(now=now)
            logger.warning("nutrition_client.scan.network ext=%s err=%s",
                           external_user_id, type(exc).__name__)
            raise NutritionUnavailableError(f"network: {type(exc).__name__}") from exc

        return self._parse_scan_response(resp, external_user_id=external_user_id)

    def _parse_scan_response(
        self, resp: httpx.Response, *, external_user_id: str,
    ) -> ScanResponse:
        now = time.monotonic()
        if resp.status_code == 200:
            self._circuit.record_success()
            body = resp.json().get("data", {})
            return ScanResponse(
                scan_id=str(body.get("id") or body.get("scan_id") or ""),
                dish_name=body.get("dish_name") or "",
                confidence=float(body.get("confidence") or 0.0),
                portion_g=body.get("portion_g"),
                nutrition=body.get("nutrition"),
                provider=body.get("provider") or "",
                raw=body,
            )

        if resp.status_code >= 500:
            self._circuit.record_failure(now=now)
            logger.warning("nutrition_client.scan.5xx status=%d ext=%s",
                           resp.status_code, external_user_id)
            raise NutritionUnavailableError(f"http_{resp.status_code}")

        # 4xx: classify by error code in body envelope.
        try:
            err_code = (resp.json().get("error") or {}).get("code", "")
        except ValueError:
            err_code = ""

        if err_code == "FOOD_NOT_RECOGNIZED":
            raise FoodNotRecognizedError("low_confidence")
        if err_code == "FOOD_API_UNAVAILABLE":
            self._circuit.record_failure(now=now)
            raise NutritionUnavailableError(err_code)

        logger.info("nutrition_client.scan.4xx status=%d ext=%s code=%s",
                    resp.status_code, external_user_id, err_code)
        raise NutritionAPIError(f"http_{resp.status_code}_{err_code or 'unknown'}")


    async def log_meal(
        self,
        *,
        external_user_id: str,
        scan_id: str | None = None,
        dish_name: str | None = None,
        meal_type: str,
        portion_multiplier: float = 1.0,
        idempotency_key: str | None = None,
    ) -> FoodLogResponse:
        """POST /api/v1/nutrition/internal/food-log/.

        At least one of scan_id / dish_name must be provided.
        """
        now = time.monotonic()
        if self._circuit.is_open(now=now):
            raise NutritionUnavailableError("circuit_open")

        url = f"{self._base_url}/api/v1/nutrition/internal/food-log/"
        headers: dict[str, str] = {
            "X-Service-Token": self._token,
            "X-External-User-ID": external_user_id,
        }
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key
        body: dict[str, Any] = {
            "meal_type": meal_type,
            "portion_multiplier": portion_multiplier,
        }
        if scan_id:
            body["scan_id"] = scan_id
        if dish_name:
            body["dish_name"] = dish_name

        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as http:
                resp = await http.post(url, headers=headers, json=body)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            self._circuit.record_failure(now=now)
            logger.warning("nutrition_client.log.network ext=%s err=%s",
                           external_user_id, type(exc).__name__)
            raise NutritionUnavailableError(f"network: {type(exc).__name__}") from exc

        return self._parse_log_response(resp, external_user_id=external_user_id)

    async def daily_summary(
        self,
        *,
        external_user_id: str,
        date: str | None = None,
    ) -> SummaryResponse:
        """GET /api/v1/nutrition/internal/summary/?date=YYYY-MM-DD."""
        now = time.monotonic()
        if self._circuit.is_open(now=now):
            raise NutritionUnavailableError("circuit_open")

        url = f"{self._base_url}/api/v1/nutrition/internal/summary/"
        headers = {
            "X-Service-Token": self._token,
            "X-External-User-ID": external_user_id,
        }
        params: dict[str, str] = {}
        if date:
            params["date"] = date

        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as http:
                resp = await http.get(url, headers=headers, params=params)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            self._circuit.record_failure(now=now)
            logger.warning("nutrition_client.summary.network ext=%s err=%s",
                           external_user_id, type(exc).__name__)
            raise NutritionUnavailableError(f"network: {type(exc).__name__}") from exc

        return self._parse_summary_response(resp, external_user_id=external_user_id)

    def _parse_log_response(
        self, resp: httpx.Response, *, external_user_id: str,
    ) -> FoodLogResponse:
        now = time.monotonic()
        if resp.status_code in (200, 201):
            self._circuit.record_success()
            body = resp.json().get("data", {})
            return FoodLogResponse(
                log_id=str(body.get("id") or ""),
                dish_name=body.get("dish_name") or "",
                meal_type=body.get("meal_type") or "",
                calories=float(body.get("calories") or 0.0),
                raw=body,
            )
        if resp.status_code >= 500:
            self._circuit.record_failure(now=now)
            raise NutritionUnavailableError(f"http_{resp.status_code}")
        try:
            err_code = (resp.json().get("error") or {}).get("code", "")
        except ValueError:
            err_code = ""
        if err_code == "FOOD_NOT_RECOGNIZED":
            raise FoodNotRecognizedError("nutrition_missing")
        raise NutritionAPIError(f"http_{resp.status_code}_{err_code or 'unknown'}")

    def _parse_summary_response(
        self, resp: httpx.Response, *, external_user_id: str,
    ) -> SummaryResponse:
        now = time.monotonic()
        if resp.status_code == 200:
            self._circuit.record_success()
            body = resp.json().get("data", {})
            return SummaryResponse(
                date=str(body.get("date") or ""),
                calories_total=float(body.get("calories_total") or 0.0),
                calories_goal=int(body.get("calories_goal") or 0),
                protein_g=float(body.get("protein_g") or 0.0),
                fat_g=float(body.get("fat_g") or 0.0),
                carbs_g=float(body.get("carbs_g") or 0.0),
                entries=list(body.get("entries") or []),
                raw=body,
            )
        if resp.status_code >= 500:
            self._circuit.record_failure(now=now)
            raise NutritionUnavailableError(f"http_{resp.status_code}")
        raise NutritionAPIError(f"http_{resp.status_code}")

    async def weekly_deficits(
        self,
        *,
        external_user_id: str,
        days: int = 7,
    ) -> DeficitsResponse:
        """GET /api/v1/nutrition/internal/deficits/?days=N — DRF-248 bridge signal."""
        now = time.monotonic()
        if self._circuit.is_open(now=now):
            raise NutritionUnavailableError("circuit_open")

        url = f"{self._base_url}/api/v1/nutrition/internal/deficits/"
        headers = {
            "X-Service-Token": self._token,
            "X-External-User-ID": external_user_id,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as http:
                resp = await http.get(url, headers=headers, params={"days": str(days)})
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            self._circuit.record_failure(now=now)
            raise NutritionUnavailableError(f"network: {type(exc).__name__}") from exc

        if resp.status_code == 200:
            self._circuit.record_success()
            body = resp.json().get("data", {})
            return DeficitsResponse(
                days_observed=int(body.get("days_observed") or 0),
                protein_avg_pct_goal=body.get("protein_avg_pct_goal"),
                protein_low_streak_days=int(body.get("protein_low_streak_days") or 0),
                hint=str(body.get("hint") or ""),
                fired_keys=list(body.get("fired_keys") or []),
                raw=body,
            )
        if resp.status_code >= 500:
            self._circuit.record_failure(now=now)
            raise NutritionUnavailableError(f"http_{resp.status_code}")
        raise NutritionAPIError(f"http_{resp.status_code}")


_SINGLETON: NutritionClient | None = None


def get_nutrition_client() -> NutritionClient:
    """Module-level singleton. Lazy — fail loudly if env not set on first use."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = NutritionClient(
            base_url=getattr(settings, "AYLA_BASE_URL", ""),
            service_token=getattr(settings, "NUTRITION_SERVICE_TOKEN", ""),
        )
    return _SINGLETON


def reset_nutrition_client() -> None:
    """Drop singleton — used by tests to reset state between cases."""
    global _SINGLETON
    _SINGLETON = None
