"""
Tests for Family Plan functionality.
"""
import pytest
from datetime import datetime, timedelta, timezone

from bot.models.family_plan import FamilyPlan, FamilyMember, FamilyInvite


class TestFamilyPlanModel:
    """Tests for FamilyPlan model properties."""

    def test_is_premium_with_future_date(self):
        """Test is_premium returns True when premium_until is in future."""
        plan = FamilyPlan(
            id=1,
            owner_id=123,
            premium_until=datetime.now(timezone.utc) + timedelta(days=30)
        )
        assert plan.is_premium is True

    def test_is_premium_with_past_date(self):
        """Test is_premium returns False when premium_until is in past."""
        plan = FamilyPlan(
            id=1,
            owner_id=123,
            premium_until=datetime.now(timezone.utc) - timedelta(days=1)
        )
        assert plan.is_premium is False

    def test_is_premium_without_date(self):
        """Test is_premium returns False when premium_until is None."""
        plan = FamilyPlan(
            id=1,
            owner_id=123,
            premium_until=None
        )
        assert plan.is_premium is False


class TestFamilyMemberModel:
    """Tests for FamilyMember model."""

    def test_member_creation(self):
        """Test FamilyMember can be created with required fields."""
        member = FamilyMember(
            id=1,
            family_plan_id=1,
            user_id=456,
            role="member"
        )
        assert member.user_id == 456
        assert member.role == "member"

    def test_owner_role(self):
        """Test FamilyMember can have owner role."""
        member = FamilyMember(
            id=1,
            family_plan_id=1,
            user_id=123,
            role="owner"
        )
        assert member.role == "owner"


class TestFamilyInviteModel:
    """Tests for FamilyInvite model."""

    def test_invite_creation(self):
        """Test FamilyInvite can be created."""
        invite = FamilyInvite(
            id=1,
            family_plan_id=1,
            invite_code="ABC123XYZ",
            uses_left=1,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=48)
        )
        assert invite.invite_code == "ABC123XYZ"
        assert invite.uses_left == 1


class TestFamilyHandlers:
    """Tests for Family Plan handlers (mocked)."""

    def test_family_handler_module_imports(self):
        """Test family handler module can be imported."""
        from bot.handlers import family
        assert hasattr(family, "router")
        assert hasattr(family, "cmd_family")
        assert hasattr(family, "_get_user_family")
        assert hasattr(family, "_get_family_members_count")


class TestFamilyI18n:
    """Tests for Family Plan i18n strings."""

    def test_ru_family_strings_exist(self):
        """Test Russian family plan strings exist."""
        import json
        from pathlib import Path
        
        ru_path = Path(__file__).parent.parent / "bot" / "i18n" / "ru.json"
        with open(ru_path, "r", encoding="utf-8") as f:
            ru = json.load(f)
        
        required_keys = [
            "family_info",
            "family_create_btn",
            "family_join_btn",
            "family_created",
            "family_status",
            "family_invite_btn",
            "family_premium_activated",
        ]
        
        for key in required_keys:
            assert key in ru, f"Missing i18n key: {key}"

    def test_en_family_strings_exist(self):
        """Test English family plan strings exist."""
        import json
        from pathlib import Path
        
        en_path = Path(__file__).parent.parent / "bot" / "i18n" / "en.json"
        with open(en_path, "r", encoding="utf-8") as f:
            en = json.load(f)
        
        required_keys = [
            "family_info",
            "family_create_btn",
            "family_join_btn",
            "family_created",
        ]
        
        for key in required_keys:
            assert key in en, f"Missing i18n key: {key}"
