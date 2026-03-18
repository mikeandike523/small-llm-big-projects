import mysql.connector
from mysql.connector import pooling

from src.utils.docker_compose import get_service_port


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
        port = get_service_port("mysql", 3306)

        _pool = pooling.MySQLConnectionPool(
            pool_name="slbp_pool",
            pool_size=10,
            pool_reset_session=True,
            host="127.0.0.1",
            port=port,
            database="slbp",
            user="slbp",
            password="slbp",
        )
    return _pool
