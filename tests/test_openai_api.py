"""tests/test_openai_api.py"""

import pytest
import os
from openai import OpenAI
from unittest.mock import patch
from dotenv import load_dotenv
load_dotenv()

@pytest.fixture
def client():
    """Fixture to create OpenAI client with API key."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not found in environment")
    return OpenAI(api_key=api_key)

def test_openai_connection(client):
    """Test that we can connect to OpenAI API."""
    assert client is not None
    assert isinstance(client, OpenAI)

def test_chat_completion(client):
    """Test basic chat completion functionality."""
    try:
        completion = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say 'test' and nothing else."}
            ],
            max_tokens=10
        )
        
        assert completion.choices is not None
        assert len(completion.choices) > 0
        assert completion.choices[0].message is not None
        # Check if response contains 'test' (case-insensitive)
        assert 'test' in completion.choices[0].message.content.lower()
        
    except Exception as e:
        pytest.fail(f"Chat completion test failed: {str(e)}")

@pytest.mark.skip(reason="Only run when checking API limits")
def test_rate_limiting(client):
    """Test rate limiting behavior (skipped by default)."""
    for i in range(3):  # Make 3 rapid requests
        completion = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "user", "content": "Say 'test'."}
            ],
            max_tokens=10
        )
        assert completion.choices[0].message is not None

if __name__ == "__main__":
    pytest.main([__file__])