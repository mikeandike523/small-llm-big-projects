from __future__ import annotations

import shutil
import tempfile
import uuid
from dataclasses import dataclass, field

import redis

from src.utils.redis_dict import RedisDict


@dataclass
class TestEnv:
    redis_client: redis.Redis
    session_data: dict
    tmp_dir: str
    _redis_hash_key: str

    def cleanup(self) -> None:
        # Delete the Redis hash
        try:
            self.redis_client.delete(self._redis_hash_key)
        except Exception:
            pass

        # Remove tmp_dir
        try:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        except Exception:
            pass


def make_env(suffix: str) -> TestEnv:
    unique = uuid.uuid4().hex[:8]
    hash_key = f"tool_test:session:{suffix}:{unique}"

    r = redis.Redis(host="localhost", port=6379, decode_responses=True)
    memory = RedisDict(r, hash_key)

    tmp_dir = tempfile.mkdtemp(prefix=f"tooltest_{suffix}_")

    session_data: dict = {
        "memory": memory,
    }

    return TestEnv(
        redis_client=r,
        session_data=session_data,
        tmp_dir=tmp_dir,
        _redis_hash_key=hash_key,
    )
