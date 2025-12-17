"""
FastAPI application for search API.
"""

import logging
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from typing import List
import psycopg2
from psycopg2.extras import RealDictCursor

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
                # First, get total count of matching messages
                count_query = """
                    SELECT COUNT(*) as total
                    FROM messages
                    WHERE search_vector @@ plainto_tsquery('english', %s)
                """
                cur.execute(count_query, (query,))
                total = cur.fetchone()['total']
                
                # Then get the paginated results with ranking
                search_query = """
                    SELECT id, user_id, user_name, timestamp, message
                    FROM messages
                    WHERE search_vector @@ plainto_tsquery('english', %s)
                    ORDER BY ts_rank(search_vector, plainto_tsquery('english', %s)) DESC
                    LIMIT %s OFFSET %s
                """
                cur.execute(search_query, (query, query, limit, offset))
                rows = cur.fetchall()
                
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

