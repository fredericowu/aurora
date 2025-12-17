"""
Lambda handler using Mangum adapter for FastAPI.
"""

from mangum import Mangum
from app import app

# Create Mangum adapter
handler = Mangum(app, lifespan="off")

