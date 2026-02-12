import subprocess
from pathlib import Path

import mysql.connector
from mysql.connector import pooling

COMPOSE_DIR = Path(__file__).resolve().parent.parent / "server"


def _get_mysql_host_port() -> int:
    """Use `docker compose port` to discover the host port mapped to mysql:3306."""
    result = subprocess.run(
        ["docker", "compose", "port", "mysql", "3306"],
        cwd=COMPOSE_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    # Output is like "0.0.0.0:12345\n"
    _, port_str = result.stdout.strip().rsplit(":", 1)
    return int(port_str)


_pool = None


def get_pool():
    """Return a connection pool pointed at the docker-compose mysql instance.

    The pool handles connection creation, health checks, and retries internally.
    Usage:
        pool = get_pool()
        conn = pool.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
    """
    global _pool
    if _pool is None:
        port = _get_mysql_host_port()
        _pool = pooling.MySQLConnectionPool(
            pool_name="slbp_pool",
            pool_size=10,
            pool_reset_session=True,
            host="localhost",
            port=port,
            database="slbp",
            user="slbp",
            password="slbp",
        )
    return _pool
