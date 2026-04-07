import pytest

from src.article_validator import ArticleValidator


@pytest.fixture
def validator():
    return ArticleValidator()


def test_xss_stripped(validator):
    article = {
        "title": '<script>alert("xss")</script>Safe Title',
        "content": '<p>Body</p><script>malicious()</script>',
        "url": "https://example.com/article",
    }

    cleaned = validator.clean_article(article)

    assert cleaned is not None
    assert "<script" not in cleaned["title"].lower()
    assert "<script" not in cleaned["content"].lower()
    assert "Safe Title" in cleaned["title"]


def test_title_length_limit(validator):
    article = {
        "title": "x" * 1000,
        "content": "valid content",
        "url": "https://example.com/article",
    }

    cleaned = validator.clean_article(article)

    assert cleaned is not None
    assert len(cleaned["title"]) == validator.MAX_TITLE_LENGTH


def test_content_length_limit(validator):
    article = {
        "title": "short",
        "content": "y" * (ArticleValidator.MAX_CONTENT_LENGTH + 10),
        "url": "https://example.com/article",
    }

    cleaned = validator.clean_article(article)

    assert cleaned is not None
    assert len(cleaned["content"]) == validator.MAX_CONTENT_LENGTH


def test_valid_url_accepted(validator):
    article = {
        "url": "https://example.com/article",
        "title": "Test",
        "content": "Content",
    }
    result = validator.clean_article(article)
    assert result is not None
    assert result["url"] == "https://example.com/article"
    assert result["title"] == "Test"
    assert result["content"] == "Content"
    assert result["published_at"] == ""


def test_invalid_url_rejected(validator):
    article = {
        "url": "not-a-url",
        "title": "Test",
        "content": "Content",
    }
    result = validator.clean_article(article)
    assert result is None


def test_script_tags_stripped(validator):
    article = {
        "url": "https://example.com",
        "title": '<script>alert(1)</script>Safe',
        "content": "OK",
    }
    result = validator.clean_article(article)
    assert result is not None
    assert "<script" not in result["title"].lower()
    assert "Safe" in result["title"]


def test_onclick_handlers_stripped(validator):
    article = {
        "url": "https://example.com",
        "title": "Test",
        "content": '<div onclick="evil()">Text</div>',
    }
    result = validator.clean_article(article)
    assert result is not None
    assert "onclick" not in result["content"].lower()
    assert "Text" in result["content"]


def test_future_date_rejected(validator):
    article = {
        "url": "https://example.com",
        "title": "Test",
        "content": "OK",
        "published_at": "2099-01-01",
    }
    result = validator.clean_article(article)
    assert result is None


def test_ancient_date_rejected(validator):
    article = {
        "url": "https://example.com",
        "title": "Test",
        "content": "OK",
        "published_at": "1800-01-01",
    }
    result = validator.clean_article(article)
    assert result is None


def test_missing_title_rejected(validator):
    article = {
        "url": "https://example.com",
        "content": "Content",
    }
    result = validator.clean_article(article)
    assert result is None


def test_empty_content_rejected(validator):
    article = {
        "url": "https://example.com",
        "title": "Test",
        "content": "",
    }
    result = validator.clean_article(article)
    assert result is None


def test_rejects_non_mapping_article_input(validator):
    result = validator.clean_article(None)
    assert result is None


def test_url_to_image_invalid_url_is_dropped(validator):
    article = {
        "url": "https://example.com",
        "title": "Test",
        "content": "Body",
        "url_to_image": "javascript:alert(1)",
    }
    result = validator.clean_article(article)
    assert result is not None
    assert result["url_to_image"] is None


def test_boundary_lengths_at_max_are_accepted(validator):
    article = {
        "url": "https://example.com",
        "title": "t" * validator.MAX_TITLE_LENGTH,
        "content": "c" * validator.MAX_CONTENT_LENGTH,
    }
    result = validator.clean_article(article)
    assert result is not None
    assert len(result["title"]) == validator.MAX_TITLE_LENGTH
    assert len(result["content"]) == validator.MAX_CONTENT_LENGTH


def test_malformed_date_rejected(validator):
    article = {
        "url": "https://example.com",
        "title": "Test",
        "content": "Body",
        "published_at": "not-a-date",
    }
    result = validator.clean_article(article)
    assert result is None

