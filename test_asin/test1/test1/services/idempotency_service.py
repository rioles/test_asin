import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Any

import redis
from django.db import IntegrityError

from ..models.idempotency_record import IdempotencyRecordModel


# Codes préfixes pour discriminer les erreurs sans créer d'exceptions custom.
# La vue fera : if str(e).startswith(ERR_HASH_MISMATCH): ...
ERR_HASH_MISMATCH = "idem:hash_mismatch:"
ERR_IN_PROGRESS = "idem:in_progress:"


class IdempotencyService:
    """
    Orchestre l'idempotence : base (source de vérité) + Redis (cache).

    Contrat public :
        - begin()    → démarre ou rejoue une requête
        - complete() → succès : persiste la réponse finale
        - fail()     → échec : persiste le FAILED (terminal)

    Exceptions levées (natives uniquement) :
        - ValueError    → hash mismatch (préfixe ERR_HASH_MISMATCH)
        - RuntimeError  → processing in progress (préfixe ERR_IN_PROGRESS)
        - IntegrityError → ne sort JAMAIS : on la catch et on la traduit
    """

    TTL_HOURS = 24
    TTL_SECONDS = TTL_HOURS * 3600

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    # ---------- Utils ----------

    @staticmethod
    def hash_payload(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _cache_key(self, user_id: str, key: str) -> str:
        return f"idempotency:{user_id}:{key}"

    def _cache_get(self, user_id: str, key: str) -> dict | None:
        try:
            raw = self.redis.get(self._cache_key(user_id, key))
            return json.loads(raw) if raw else None
        except redis.RedisError:
            return None

    def _cache_set(self, user_id: str, key: str, payload: dict) -> None:
        try:
            self.redis.set(
                self._cache_key(user_id, key),
                json.dumps(payload),
                ex=self.TTL_SECONDS,
            )
        except redis.RedisError:
            pass  # cache raté : pas grave, la base a la vérité

    # ---------- API publique ----------

    def begin(
        self, user_id: str, key: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Retourne { status, response_code, response_body }.

        - COMPLETED/FAILED existant → renvoyé tel quel (le caller rejoue).
        - Nouveau → status="PROCESSING" (le caller exécute la logique métier).
        - PROCESSING existant → lève RuntimeError(ERR_IN_PROGRESS + ...).
        - Hash différent      → lève ValueError(ERR_HASH_MISMATCH + ...).
        """
        request_hash = self.hash_payload(payload)

        # 1. Fast path : Redis
        cached = self._cache_get(user_id, key)
        if cached:
            if cached["request_hash"] != request_hash:
                raise ValueError(f"{ERR_HASH_MISMATCH}{user_id}:{key}")
            if cached["status"] == "PROCESSING":
                raise RuntimeError(f"{ERR_IN_PROGRESS}{user_id}:{key}")
            return cached  # COMPLETED ou FAILED → à rejouer

        # 2. Slow path : base (autorité)
        try:
            IdempotencyRecordModel.objects.create(
                user_id=user_id,
                key=key,
                request_hash=request_hash,
                status=IdempotencyRecordModel.Status.PROCESSING,
                expires_at=datetime.now(timezone.utc)
                + timedelta(hours=self.TTL_HOURS),
            )
            self._cache_set(
                user_id,
                key,
                {
                    "request_hash": request_hash,
                    "status": "PROCESSING",
                    "response_code": None,
                    "response_body": None,
                },
            )
            return {
                "status": "PROCESSING",
                "response_code": None,
                "response_body": None,
            }
        except IntegrityError:
            # Un autre process a la clé. On lit en base.
            record = IdempotencyRecordModel.objects.get(user_id=user_id, key=key)

            if record.request_hash != request_hash:
                raise ValueError(f"{ERR_HASH_MISMATCH}{user_id}:{key}")

            if record.status == IdempotencyRecordModel.Status.PROCESSING:
                self._cache_set(
                    user_id,
                    key,
                    {
                        "request_hash": request_hash,
                        "status": "PROCESSING",
                        "response_code": None,
                        "response_body": None,
                    },
                )
                raise RuntimeError(f"{ERR_IN_PROGRESS}{user_id}:{key}")

            # COMPLETED ou FAILED → on réhydrate le cache et on rejoue
            result = {
                "request_hash": request_hash,
                "status": record.status,
                "response_code": record.response_code,
                "response_body": record.response_body,
            }
            self._cache_set(user_id, key, result)
            return result

    def complete(self, user_id: str, key: str, code: int, body: dict) -> None:
        """Écrit la réponse finale : base d'abord, puis cache."""
        IdempotencyRecordModel.objects.filter(user_id=user_id, key=key).update(
            status=IdempotencyRecordModel.Status.COMPLETED,
            response_code=code,
            response_body=body,
        )
        record = (
            IdempotencyRecordModel.objects.filter(user_id=user_id, key=key)
            .only("request_hash")
            .first()
        )
        if record:
            self._cache_set(
                user_id,
                key,
                {
                    "request_hash": record.request_hash,
                    "status": "COMPLETED",
                    "response_code": code,
                    "response_body": body,
                },
            )

    def fail(self, user_id: str, key: str, reason: str) -> None:
        """FAILED est terminal. On stocke, on ne supprime pas."""
        IdempotencyRecordModel.objects.filter(user_id=user_id, key=key).update(
            status=IdempotencyRecordModel.Status.FAILED,
            response_code=500,
            response_body={"error": reason},
        )
        record = (
            IdempotencyRecordModel.objects.filter(user_id=user_id, key=key)
            .only("request_hash")
            .first()
        )
        if record:
            self._cache_set(
                user_id,
                key,
                {
                    "request_hash": record.request_hash,
                    "status": "FAILED",
                    "response_code": 500,
                    "response_body": {"error": reason},
                },
            )