"""
Customer feedback (star rating + optional comment) submitted from the
public tracking page after a delivery is marked "Delivered". One
feedback submission per delivery — enforced at the database level via a
unique constraint on delivery_id, not just in application code.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime
from pydantic import BaseModel, Field
from typing import Optional

from app.db.session import Base


class DeliveryFeedbackDB(Base):
    __tablename__ = "delivery_feedback"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    delivery_id = Column(String, unique=True, index=True, nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class FeedbackSubmit(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = None


class FeedbackOut(BaseModel):
    rating: int
    comment: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
