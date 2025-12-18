"""
Database connection pool management for PostgreSQL.
"""

import os
import logging
import psycopg2
from psycopg2 import pool
from contextlib import contextmanager
from typing import Generator, Optional

logger = logging.getLogger(__name__)

# Global connection pool
_connection_pool: Optional[pool.SimpleConnectionPool] = None


def get_db_config():
    """Get database configuration from environment variables."""
    return {
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT', '5432'),
        'database': os.getenv('DB_NAME', 'messages'),
        'user': os.getenv('DB_USER', 'postgres'),
        'password': os.getenv('DB_PASSWORD'),
    }


def init_connection_pool():
    """Initialize the database connection pool."""
    global _connection_pool
    
    if _connection_pool is not None:
        return
    
    db_config = get_db_config()
    
    # Validate required config
    if not all([db_config['host'], db_config['password']]):
        raise ValueError("Missing required database configuration")
    
    try:
        # With RDS Proxy, we can use a smaller pool since proxy handles pooling
        # This reduces Lambda memory usage and connection overhead
        _connection_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1,
            maxconn=2,
            connect_timeout=5,
            **db_config
        )
        logger.info("Database connection pool initialized")
    except Exception as e:
        logger.error(f"Error initializing connection pool: {e}")
        raise


def get_connection_pool() -> pool.SimpleConnectionPool:
    """Get the database connection pool, initializing if necessary."""
    if _connection_pool is None:
        init_connection_pool()
    return _connection_pool


@contextmanager
def get_db_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """Get a database connection from the pool (context manager)."""
    pool = get_connection_pool()
    conn = None
    try:
        conn = pool.getconn()
        yield conn
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database connection error: {e}")
        raise
    finally:
        if conn:
            pool.putconn(conn)


def close_connection_pool():
    """Close all connections in the pool."""
    global _connection_pool
    if _connection_pool:
        _connection_pool.closeall()
        _connection_pool = None
        logger.info("Database connection pool closed")

