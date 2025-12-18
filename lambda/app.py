"""
FastAPI application for search API.
"""

import logging
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from typing import List, Dict, Optional
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
import requests
from urllib.parse import urljoin

from models import Message, PaginatedMessages
from database import get_db_connection

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Aurora Search API",
    description="Search engine API for messages using PostgreSQL tsvector",
    version="1.0.0"
)


def search_messages(query: str, page: int = 0, limit: int = 10) -> PaginatedMessages:
    """
    Search messages using PostgreSQL tsvector full-text search.
    
    Args:
        query: Search query string
        page: Page number (0-indexed)
        limit: Number of results per page
        
    Returns:
        PaginatedMessages with search results
    """
    offset = page * limit
    
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                # Single optimized query: get results and total count together
                # Using window function COUNT(*) OVER() to get total without separate query
                # Using 'simple' configuration for no stop words and no stemming
                search_query = """
                    SELECT 
                        id, 
                        user_id, 
                        user_name, 
                        timestamp, 
                        message,
                        COUNT(*) OVER() as total_count
                    FROM messages
                    WHERE search_vector @@ plainto_tsquery('simple', %s)
                    ORDER BY ts_rank(search_vector, plainto_tsquery('simple', %s)) DESC
                    LIMIT %s OFFSET %s
                """
                cur.execute(search_query, (query, query, limit, offset))
                rows = cur.fetchall()
                
                # Extract total from first row, or 0 if no results
                total = rows[0]['total_count'] if rows else 0
                
                # Convert rows to Message objects
                messages = [
                    Message(
                        id=row['id'],
                        user_id=row['user_id'],
                        user_name=row['user_name'],
                        timestamp=str(row['timestamp']),
                        message=row['message']
                    )
                    for row in rows
                ]
                
                return PaginatedMessages(total=total, items=messages)
                
            except psycopg2.Error as e:
                logger.error(f"Database error during search: {e}")
                raise HTTPException(status_code=500, detail="Database error")
            except Exception as e:
                logger.error(f"Unexpected error during search: {e}")
                raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/", tags=["Health"])
async def root():
    """Root endpoint for health check."""
    return {"status": "ok", "service": "aurora-search-api"}


@app.get("/search", response_model=PaginatedMessages, tags=["Search"])
async def search(
    q: str = Query(..., description="Search query string", min_length=1),
    page: int = Query(0, ge=0, description="Page number (0-indexed)"),
    limit: int = Query(10, ge=1, le=100, description="Number of results per page")
):
    """
    Search messages using full-text search.
    
    Returns paginated results matching the search query.
    """
    try:
        result = search_messages(q, page, limit)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in search endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/health", tags=["Health"])
async def health():
    """Health check endpoint."""
    try:
        # Test database connection
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


# Ingestion functionality
API_BASE_URL = "https://november7-730026606190.europe-west1.run.app"
MESSAGES_ENDPOINT = "/messages/"
PAGE_SIZE = 100


def init_database(conn):
    """Initialize database schema with messages table and tsvector support."""
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
        # Using 'simple' configuration for no stop words and no stemming
        cur.execute("""
            CREATE OR REPLACE FUNCTION messages_search_vector_update()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.search_vector := to_tsvector('simple', NEW.message);
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


@app.post("/ingest", tags=["Admin"])
async def ingest_messages():
    """
    Ingest messages from external API into the database.
    
    This endpoint fetches all messages from the external API with pagination
    and stores them in the database with deduplication.
    """
    try:
        logger.info("Starting message ingestion...")
        
        with get_db_connection() as conn:
            # Initialize database schema
            init_database(conn)
            
            total_ingested = 0
            skip = 0
            
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
                store_messages(conn, items)
                
                page_count = len(items)
                total_ingested += page_count
                
                logger.info(f"Stored {page_count} messages (total so far: {total_ingested})")
                
                # Check if we've fetched all messages
                if skip + len(items) >= total:
                    logger.info(f"Reached total of {total} messages")
                    break
                
                skip += PAGE_SIZE
                
                # Safety check to prevent infinite loops
                if skip > 1000000:
                    logger.warning("Reached safety limit, stopping ingestion")
                    break
        
        logger.info(f"Ingestion complete. Total messages processed: {total_ingested}")
        return {
            "status": "success",
            "messages_processed": total_ingested,
            "message": f"Successfully ingested {total_ingested} messages"
        }
        
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")

