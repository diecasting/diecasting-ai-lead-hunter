"""Tests for the lead ranking engine (Phase 2.3, section 5).

Verifies the priority thresholds:
  HIGH    >= 80
  MEDIUM  50-79
  LOW     < 50
"""
from app.ai.ranking import (
    HIGH,
    LOW,
    MEDIUM,
    primary_score,
    rank_lead,
    rank_with_detail,
    score_to_priority,
)


class TestScoreToPriority:
    def test_high_at_80(self):
        assert score_to_priority(80) == "HIGH"

    def test_high_at_100(self):
        assert score_to_priority(100) == "HIGH"

    def test_medium_at_50(self):
        assert score_to_priority(50) == "MEDIUM"

    def test_medium_at_79(self):
        assert score_to_priority(79) == "MEDIUM"

    def test_low_at_49(self):
        assert score_to_priority(49) == "LOW"

    def test_low_at_0(self):
        assert score_to_priority(0) == "LOW"

    def test_high_threshold_is_80(self):
        """The boundary between MEDIUM and HIGH is exactly 80."""
        assert score_to_priority(79) == "MEDIUM"
        assert score_to_priority(80) == "HIGH"

    def test_medium_threshold_is_50(self):
        """The boundary between LOW and MEDIUM is exactly 50."""
        assert score_to_priority(49) == "LOW"
        assert score_to_priority(50) == "MEDIUM"


class TestPrimaryScore:
    def test_returns_max_of_three(self):
        assert primary_score(30, 50, 10) == 50

    def test_casting_highest(self):
        assert primary_score(90, 30, 20) == 90

    def test_cnc_highest(self):
        assert primary_score(20, 85, 30) == 85

    def test_tooling_highest(self):
        assert primary_score(10, 20, 95) == 95

    def test_all_zero(self):
        assert primary_score(0, 0, 0) == 0

    def test_all_equal(self):
        assert primary_score(60, 60, 60) == 60

    def test_none_treated_as_zero(self):
        assert primary_score(None, None, None) == 0


class TestRankLead:
    def test_high_priority(self):
        scores = {"casting_need_score": 90, "cnc_need_score": 30, "tooling_need_score": 20}
        assert rank_lead(scores) == "HIGH"

    def test_medium_priority(self):
        scores = {"casting_need_score": 60, "cnc_need_score": 30, "tooling_need_score": 20}
        assert rank_lead(scores) == "MEDIUM"

    def test_low_priority(self):
        scores = {"casting_need_score": 10, "cnc_need_score": 20, "tooling_need_score": 5}
        assert rank_lead(scores) == "LOW"

    def test_missing_keys_default_to_zero(self):
        scores = {}
        assert rank_lead(scores) == "LOW"

    def test_cnc_drives_high(self):
        scores = {"casting_need_score": 10, "cnc_need_score": 85, "tooling_need_score": 5}
        assert rank_lead(scores) == "HIGH"

    def test_tooling_drives_medium(self):
        scores = {"casting_need_score": 0, "cnc_need_score": 0, "tooling_need_score": 55}
        assert rank_lead(scores) == "MEDIUM"


class TestRankWithDetail:
    def test_returns_priority_and_primary_score(self):
        result = rank_with_detail(90, 30, 20)
        assert result["priority"] == "HIGH"
        assert result["primary_score"] == 90

    def test_returns_all_scores(self):
        result = rank_with_detail(80, 50, 30)
        assert result["casting_need_score"] == 80
        assert result["cnc_need_score"] == 50
        assert result["tooling_need_score"] == 30

    def test_low_priority_detail(self):
        result = rank_with_detail(10, 5, 0)
        assert result["priority"] == "LOW"
        assert result["primary_score"] == 10

    def test_medium_boundary(self):
        result = rank_with_detail(50, 0, 0)
        assert result["priority"] == "MEDIUM"
        assert result["primary_score"] == 50

    def test_high_boundary(self):
        result = rank_with_detail(80, 0, 0)
        assert result["priority"] == "HIGH"
        assert result["primary_score"] == 80


class TestConstants:
    def test_high_constant(self):
        assert HIGH == "HIGH"

    def test_medium_constant(self):
        assert MEDIUM == "MEDIUM"

    def test_low_constant(self):
        assert LOW == "LOW"
