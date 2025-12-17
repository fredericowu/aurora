"""
Pydantic models for request/response validation.
"""

from pydantic import BaseModel, Field
from typing import List, Optional


class Message(BaseModel):
    """Message model matching the external API structure."""
    id: str
    user_id: str
    user_name: str
    timestamp: str
    message: str

    class Config:
        json_schema_extra = {
            "example": {
                "id": "msg_123",
                "user_id": "user_456",
                "user_name": "John Doe",
                "timestamp": "2024-01-01T00:00:00Z",
                "message": "This is a sample message"
            }
        }


class PaginatedMessages(BaseModel):
    """Paginated response model matching the external API structure."""
    total: int = Field(..., description="Total number of messages")
    items: List[Message] = Field(..., description="List of messages")

    class Config:
        json_schema_extra = {
            "example": {
                "total": 100,
                "items": [
                    {
                        "id": "msg_123",
                        "user_id": "user_456",
                        "user_name": "John Doe",
                        "timestamp": "2024-01-01T00:00:00Z",
                        "message": "This is a sample message"
                    }
                ]
            }
        }


class SearchQuery(BaseModel):
    """Search query parameters."""
    q: str = Field(..., description="Search query string", min_length=1)
    page: int = Field(default=0, ge=0, description="Page number (0-indexed)")
    limit: int = Field(default=10, ge=1, le=100, description="Number of results per page")

