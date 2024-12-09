"""src/models.py"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, HttpUrl, Field, field_validator

class ArticleData(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    source_name: str = Field(..., min_length=1, max_length=100)
    url: HttpUrl
    url_to_image: Optional[HttpUrl] = None
    published_at: datetime
    author: Optional[str] = None
    description: Optional[str] = None

    @field_validator('title')
    @classmethod
    def validate_title(cls, v):
        if v.strip() == '':
            raise ValueError('Title cannot be empty or whitespace')
        return v.strip()

    @field_validator('content')
    @classmethod
    def validate_content(cls, v):
        if v.strip() == '':
            raise ValueError('Content cannot be empty or whitespace')
        return v.strip()