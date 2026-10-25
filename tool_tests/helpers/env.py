from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass


@dataclass
class TestEnv:
    session_data: dict
    tmp_dir: str

    def cleanup(self) -> None:
        # Remove tmp_dir
        try:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        except Exception:
            pass


def make_env(suffix: str) -> TestEnv:
    # Session memory is a dict to the tools (in the server it is a
    # SessionMemory over MySQL rows), so a plain dict stands in for it here.
    tmp_dir = tempfile.mkdtemp(prefix=f"tooltest_{suffix}_")

    session_data: dict = {
        "memory": {},
    }

    return TestEnv(
        session_data=session_data,
        tmp_dir=tmp_dir,
    )
