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
    test_project: str
    tmp_dir: str
    _redis_hash_key: str

    def cleanup(self) -> None:
        # Delete the Redis hash
        try:
            self.redis_client.delete(self._redis_hash_key)
        except Exception:
            pass

        # Delete all project_memory rows for test_project
        try:
            from src.data import get_pool
            from src.utils.sql.kv_manager import KVManager

            pool = get_pool()
            with pool.get_connection() as conn:
                kv = KVManager(conn)
                keys = kv.list_keys(project=self.test_project)
                for k in keys:
                    kv.delete_value(k, project=self.test_project)
                conn.commit()
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
    test_project = f"/test_project/{suffix}/{unique}"

    session_data: dict = {
        "memory": memory,
        "__pinned_project__": test_project,
    }

    return TestEnv(
        redis_client=r,
        session_data=session_data,
        test_project=test_project,
        tmp_dir=tmp_dir,
        _redis_hash_key=hash_key,
    )
