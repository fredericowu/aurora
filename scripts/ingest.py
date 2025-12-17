#!/usr/bin/env python3
"""
Ingestion script to fetch messages from external API and store in PostgreSQL.
Deduplicates by id and creates tsvector indexes for full-text search.
"""

import os
import sys
import logging
import psycopg2
from psycopg2.extras import execute_values
from psycopg2.pool import SimpleConnectionPool
import requests
from typing import List, Dict, Optional
from urllib.parse import urljoin

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
API_BASE_URL = "https://november7-730026606190.europe-west1.run.app"
MESSAGES_ENDPOINT = "/messages/"
PAGE_SIZE = 100

# Database configuration from environment variables
DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'port': os.getenv('DB_PORT', '5432'),
    'database': os.getenv('DB_NAME', 'messages'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD'),
}


def get_db_connection():
    """Get database connection from pool."""
    return psycopg2.connect(**DB_CONFIG)


def init_database():
    """Initialize database schema with messages table and tsvector support."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Create messages table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL,
                    user_name VARCHAR NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    message TEXT NOT NULL,
                    search_vector TSVECTOR
                )
            """)
            
            # Create GIN index on search_vector for fast full-text search
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_search_vector 
                ON messages USING GIN(search_vector)
            """)
            
            # Create trigger function to auto-update search_vector
            cur.execute("""
                CREATE OR REPLACE FUNCTION messages_search_vector_update()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.search_vector := to_tsvector('english', NEW.message);
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            # Create trigger
            cur.execute("""
                DROP TRIGGER IF EXISTS messages_search_vector_trigger ON messages;
                CREATE TRIGGER messages_search_vector_trigger
                BEFORE INSERT OR UPDATE ON messages
                FOR EACH ROW
                EXECUTE FUNCTION messages_search_vector_update();
            """)
            
            # Create index on id for faster lookups
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_id ON messages(id)
            """)
            
            conn.commit()
            logger.info("Database schema initialized successfully")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error initializing database: {e}")
        raise
    finally:
        conn.close()


def fetch_messages_page(skip: int, limit: int) -> Optional[Dict]:
    """Fetch a page of messages from the external API."""
    url = urljoin(API_BASE_URL, MESSAGES_ENDPOINT)
    params = {'skip': skip, 'limit': limit}
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching messages page (skip={skip}, limit={limit}): {e}")
        return None


def store_messages(conn, messages: List[Dict]):
    """Store messages in database, using ON CONFLICT to handle duplicates."""
    if not messages:
        return
    
    with conn.cursor() as cur:
        # Use execute_values for bulk insert with conflict handling
        insert_query = """
            INSERT INTO messages (id, user_id, user_name, timestamp, message)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                user_name = EXCLUDED.user_name,
                timestamp = EXCLUDED.timestamp,
                message = EXCLUDED.message
        """
        
        values = [
            (
                msg['id'],
                msg['user_id'],
                msg['user_name'],
                msg['timestamp'],
                msg['message']
            )
            for msg in messages
        ]
        
        execute_values(cur, insert_query, values)
        conn.commit()


def ingest_all_messages():
    """Main ingestion function that fetches all messages with pagination."""
    logger.info("Starting message ingestion...")
    
    # Initialize database schema
    init_database()
    
    conn = get_db_connection()
    total_ingested = 0
    total_skipped = 0
    skip = 0
    
    try:
        while True:
            logger.info(f"Fetching messages page: skip={skip}, limit={PAGE_SIZE}")
            data = fetch_messages_page(skip, skip + PAGE_SIZE)
            
            if not data:
                logger.warning(f"No data received for page starting at {skip}")
                break
            
            items = data.get('items', [])
            total = data.get('total', 0)
            
            if not items:
                logger.info("No more items to fetch")
                break
            
            # Store messages (deduplication handled by ON CONFLICT)
            before_count = total_ingested
            store_messages(conn, items)
            
            # Count how many were actually new (simplified - actual count would require query)
            page_count = len(items)
            total_ingested += page_count
            
            logger.info(f"Stored {page_count} messages (total so far: {total_ingested})")
            
            # Check if we've fetched all messages
            if skip + len(items) >= total:
                logger.info(f"Reached total of {total} messages")
                break
            
            skip += PAGE_SIZE
            
            # Safety check to prevent infinite loops
            if skip > 1000000:  # Arbitrary large number
                logger.warning("Reached safety limit, stopping ingestion")
                break
    
    except Exception as e:
        logger.error(f"Error during ingestion: {e}")
        raise
    finally:
        conn.close()
    
    logger.info(f"Ingestion complete. Total messages processed: {total_ingested}")
    return total_ingested


if __name__ == "__main__":
    # Validate required environment variables
    required_vars = ['DB_HOST', 'DB_PASSWORD']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        sys.exit(1)
    
    try:
        total = ingest_all_messages()
        logger.info(f"Successfully ingested {total} messages")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        sys.exit(1)

