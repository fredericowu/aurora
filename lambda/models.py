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
    total: int = Field(
        ..., 
        description="Total number of messages matching the search query (across all pages)",
        examples=[72, 150, 23]
    )
    items: List[Message] = Field(
        ..., 
        description="List of messages for the current page",
        examples=[[
            {
                "id": "msg_123",
                "user_id": "user_456",
                "user_name": "John Doe",
                "timestamp": "2024-01-01T00:00:00Z",
                "message": "Looking for a luxury car rental in Paris"
            },
            {
                "id": "msg_124",
                "user_id": "user_789",
                "user_name": "Jane Smith",
                "timestamp": "2024-01-02T10:30:00Z",
                "message": "Need a car service to the airport tomorrow"
            }
        ]]
    )

    class Config:
        json_schema_extra = {
            "example": {
                "total": 72,
                "items": [
                    {
                        "id": "msg_123",
                        "user_id": "user_456",
                        "user_name": "John Doe",
                        "timestamp": "2024-01-01T00:00:00Z",
                        "message": "Looking for a luxury car rental in Paris"
                    },
                    {
                        "id": "msg_124",
                        "user_id": "user_789",
                        "user_name": "Jane Smith",
                        "timestamp": "2024-01-02T10:30:00Z",
                        "message": "Need a car service to the airport tomorrow"
                    }
                ]
            }
        }


class SearchQuery(BaseModel):
    """Search query parameters."""
    q: str = Field(..., description="Search query string", min_length=1)
    page: int = Field(default=0, ge=0, description="Page number (0-indexed)")
    limit: int = Field(default=10, ge=1, le=100, description="Number of results per page")

