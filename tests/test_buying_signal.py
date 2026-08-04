"""Tests for buying-signal detection (Phase 2.3, section 3).

Verifies that ``detect_buying_signal`` correctly classifies purchase intent
into HIGH / MEDIUM / LOW / NONE and returns matched phrases.
"""
from app.ai.scoring import detect_buying_signal


class TestBuyingSignalHigh:
    def test_looking_for_suppliers(self):
        result = detect_buying_signal("We are looking for suppliers of aluminum castings.")
        assert result["level"] == "HIGH"
        assert "looking for suppliers" in result["matched"]

    def test_new_supplier(self):
        result = detect_buying_signal("Seeking a new supplier for die casting parts.")
        assert result["level"] == "HIGH"
        assert "new supplier" in result["matched"]

    def test_oem_partner(self):
        result = detect_buying_signal("We need an OEM partner for production.")
        assert result["level"] == "HIGH"
        assert "oem partner" in result["matched"]

    def test_sourcing(self):
        result = detect_buying_signal("Currently sourcing CNC machining services.")
        assert result["level"] == "HIGH"
        assert "sourcing" in result["matched"]

    def test_contract_manufacturing(self):
        result = detect_buying_signal("Looking for contract manufacturing partners.")
        assert result["level"] == "HIGH"
        assert "contract manufacturing" in result["matched"]

    def test_rfq(self):
        result = detect_buying_signal("Please submit your RFQ for review.")
        assert result["level"] == "HIGH"
        assert "rfq" in result["matched"]

    def test_high_wins_over_medium(self):
        """If both HIGH and MEDIUM signals are present, HIGH wins."""
        text = "Looking for suppliers. We are a manufacturer with production capability."
        result = detect_buying_signal(text)
        assert result["level"] == "HIGH"

    def test_high_wins_over_low(self):
        text = "Looking for suppliers. We are also a distributor."
        result = detect_buying_signal(text)
        assert result["level"] == "HIGH"


class TestBuyingSignalMedium:
    def test_manufacturer(self):
        result = detect_buying_signal("We are a manufacturer of custom parts.")
        assert result["level"] == "MEDIUM"
        assert "manufacturer" in result["matched"]

    def test_production_capability(self):
        result = detect_buying_signal("Our production capability includes die casting.")
        assert result["level"] == "MEDIUM"
        assert "production capability" in result["matched"]

    def test_custom_parts(self):
        result = detect_buying_signal("We make custom parts for automotive.")
        assert result["level"] == "MEDIUM"
        assert "custom parts" in result["matched"]

    def test_medium_wins_over_low(self):
        text = "We are a manufacturer and also a distributor."
        result = detect_buying_signal(text)
        assert result["level"] == "MEDIUM"


class TestBuyingSignalLow:
    def test_distributor(self):
        result = detect_buying_signal("We are a distributor of industrial products.")
        assert result["level"] == "LOW"
        assert "distributor" in result["matched"]

    def test_trader(self):
        result = detect_buying_signal("We are a trader of metal components.")
        assert result["level"] == "LOW"
        assert "trader" in result["matched"]

    def test_trading_company(self):
        result = detect_buying_signal("We are a trading company based in Shanghai.")
        assert result["level"] == "LOW"
        assert "trading company" in result["matched"]


class TestBuyingSignalNone:
    def test_no_signals(self):
        result = detect_buying_signal("We are a software company that builds apps.")
        assert result["level"] == "NONE"
        assert result["matched"] == []

    def test_empty_text(self):
        result = detect_buying_signal("")
        assert result["level"] == "NONE"

    def test_none_text(self):
        result = detect_buying_signal(None)
        assert result["level"] == "NONE"

    def test_detail_message(self):
        result = detect_buying_signal("We are looking for suppliers.")
        assert "looking for suppliers" in result["detail"]

    def test_no_signal_detail(self):
        result = detect_buying_signal("Hello world.")
        assert "no explicit buying signal" in result["detail"]


class TestBuyingSignalMultiple:
    def test_multiple_high_signals(self):
        text = "Looking for suppliers and seeking contract manufacturing. Also sourcing new supplier."
        result = detect_buying_signal(text)
        assert result["level"] == "HIGH"
        assert len(result["matched"]) >= 3

    def test_mixed_levels_all_collected(self):
        text = "Looking for suppliers. We are a manufacturer. Also a distributor."
        result = detect_buying_signal(text)
        # HIGH wins for the level
        assert result["level"] == "HIGH"
        # But all matched phrases are collected
        assert "looking for suppliers" in result["matched"]
        assert "manufacturer" in result["matched"]
        assert "distributor" in result["matched"]
