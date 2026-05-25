import pytest

from hermes_db_mcp.repositories.inspiration_repo import VALID_CATEGORIES


class TestValidation:
    def test_valid_categories(self):
        expected = {"hook", "scene", "setting", "character", "conflict", "world", "plot"}
        assert VALID_CATEGORIES == expected

    def test_category_check(self):
        assert "hook" in VALID_CATEGORIES
        assert "invalid" not in VALID_CATEGORIES
