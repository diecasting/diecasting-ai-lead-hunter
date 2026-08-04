"""Tests for the industrial keyword library and scoring detectors (Phase 2.3).

Covers:
* Keyword bank completeness (materials, processes, industries).
* ``detect_materials`` / ``detect_processes`` / ``detect_industries`` helpers.
* ``casting_need_score`` / ``cnc_need_score`` / ``tooling_need_score``.
* ``business_type`` inference.
* ``detect_products``.
"""
from app.ai.keywords import BUYING_SIGNALS, INDUSTRIES, MATERIALS, PROCESSES
from app.ai.scoring import (
    build_analysis,
    business_type,
    casting_need_score,
    cnc_need_score,
    detect_industries,
    detect_materials,
    detect_processes,
    detect_products,
    tooling_need_score,
)


# ---------------------------------------------------------------------------
# Keyword library completeness
# ---------------------------------------------------------------------------
class TestKeywordLibrary:
    def test_materials_include_required_terms(self):
        required = ["aluminum", "aluminium", "adc12", "a380", "6061", "7075", "magnesium", "az91"]
        for term in required:
            assert term in MATERIALS, f"Missing material: {term}"

    def test_processes_include_required_terms(self):
        required = [
            "die casting", "pressure casting", "gravity casting", "sand casting",
            "investment casting", "cnc machining", "5 axis machining",
            "precision machining", "tooling", "mold",
        ]
        for term in required:
            assert term in PROCESSES, f"Missing process: {term}"

    def test_industries_include_required_terms(self):
        required = [
            "automotive", "ev", "electric vehicle", "battery", "motor housing",
            "gearbox", "pump", "hydraulic", "robotics", "industrial equipment",
            "aerospace",
        ]
        for term in required:
            assert term in INDUSTRIES, f"Missing industry: {term}"

    def test_buying_signals_have_three_levels(self):
        assert "HIGH" in BUYING_SIGNALS
        assert "MEDIUM" in BUYING_SIGNALS
        assert "LOW" in BUYING_SIGNALS

    def test_buying_signal_high_phrases(self):
        required = ["looking for suppliers", "new supplier", "oem partner", "sourcing", "contract manufacturing"]
        for phrase in required:
            assert phrase in BUYING_SIGNALS["HIGH"], f"Missing HIGH signal: {phrase}"

    def test_buying_signal_medium_phrases(self):
        required = ["manufacturer", "production capability", "custom parts"]
        for phrase in required:
            assert phrase in BUYING_SIGNALS["MEDIUM"], f"Missing MEDIUM signal: {phrase}"

    def test_buying_signal_low_phrases(self):
        required = ["distributor", "trader"]
        for phrase in required:
            assert phrase in BUYING_SIGNALS["LOW"], f"Missing LOW signal: {phrase}"


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------
class TestDetectMaterials:
    def test_detects_aluminum_and_magnesium(self):
        text = "We specialize in aluminum and magnesium die casting components."
        found = detect_materials(text)
        assert "aluminum" in found
        assert "magnesium" in found

    def test_detects_alloy_codes(self):
        text = "Our products use ADC12 and A380 alloys, also AZ91."
        found = detect_materials(text)
        assert "adc12" in found
        assert "a380" in found
        assert "az91" in found

    def test_detects_aluminium_british_spelling(self):
        text = "We produce aluminium castings for European markets."
        found = detect_materials(text)
        assert "aluminium" in found

    def test_no_materials_found(self):
        text = "We sell shoes and clothing."
        found = detect_materials(text)
        assert found == []

    def test_respects_limit(self):
        text = "aluminum aluminium adc12 a380 6061 7075 magnesium az91 zinc zamak"
        found = detect_materials(text, limit=3)
        assert len(found) <= 3


class TestDetectProcesses:
    def test_detects_die_casting(self):
        text = "Our company offers die casting and CNC machining services."
        found = detect_processes(text)
        assert "die casting" in found
        assert "cnc machining" in found

    def test_detects_investment_casting(self):
        text = "We provide investment casting for aerospace parts."
        found = detect_processes(text)
        assert "investment casting" in found

    def test_detects_mold_and_mould(self):
        text = "We design mold and mould tools for our customers."
        found = detect_processes(text)
        assert "mold" in found
        assert "mould" in found


class TestDetectIndustries:
    def test_detects_automotive_and_ev(self):
        text = "We serve the automotive and EV sectors with precision parts."
        found = detect_industries(text)
        assert "automotive" in found
        assert "ev" in found

    def test_detects_aerospace(self):
        text = "Aerospace-grade components are our specialty."
        found = detect_industries(text)
        assert "aerospace" in found

    def test_detects_robotics_and_hydraulic(self):
        text = "We make parts for robotics and hydraulic systems."
        found = detect_industries(text)
        assert "robotics" in found
        assert "hydraulic" in found


class TestDetectProducts:
    def test_detects_products(self):
        text = "We offer die casting, CNC machining, and precision machining."
        found = detect_products(text)
        assert "die casting" in found
        assert "cnc machining" in found
        assert "precision machining" in found

    def test_detects_hpdc(self):
        text = "Our HPDC capabilities cover high pressure die casting."
        found = detect_products(text)
        assert "hpdc" in found


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
class TestCastingNeedScore:
    def test_high_score_for_automotive_aluminum_die_casting(self):
        text = "Aluminum die casting for automotive EV components."
        score = casting_need_score(text)
        assert score >= 80

    def test_moderate_score_for_sand_casting_only(self):
        text = "We do sand casting for pumps."
        score = casting_need_score(text)
        assert 15 <= score < 80

    def test_zero_score_for_unrelated(self):
        text = "We are a software company."
        score = casting_need_score(text)
        assert score == 0

    def test_score_capped_at_100(self):
        text = " ".join([
            "aluminum", "aluminium", "magnesium", "adc12", "a380", "az91",
            "zamak", "zinc", "die casting", "pressure casting", "gravity casting",
            "sand casting", "investment casting", "automotive", "ev",
            "electric vehicle", "aerospace", "battery", "motor housing",
            "gearbox", "pump", "hydraulic", "robotics", "industrial equipment",
        ])
        score = casting_need_score(text)
        assert score == 100


class TestCncNeedScore:
    def test_high_score_for_cnc_and_5_axis(self):
        text = "CNC machining and 5 axis machining of 7075 aluminum parts."
        score = cnc_need_score(text)
        assert score >= 80

    def test_moderate_for_precision_machining(self):
        text = "We offer precision machining services."
        score = cnc_need_score(text)
        assert score >= 25

    def test_zero_for_no_cnc(self):
        text = "We sell raw materials."
        score = cnc_need_score(text)
        assert score == 0


class TestToolingNeedScore:
    def test_high_score_for_tooling_and_mold(self):
        text = "We design tooling and mold for die casting."
        score = tooling_need_score(text)
        assert score >= 50

    def test_moderate_for_mold_only(self):
        text = "We make mold components."
        score = tooling_need_score(text)
        assert score >= 25

    def test_zero_for_no_tooling(self):
        text = "We are a logistics company."
        score = tooling_need_score(text)
        assert score == 0


# ---------------------------------------------------------------------------
# Business type inference
# ---------------------------------------------------------------------------
class TestBusinessType:
    def test_manufacturer(self):
        assert business_type("We are a manufacturer of die cast parts.") == "Manufacturer / OEM"

    def test_oem(self):
        assert business_type("OEM production facility for automotive.") == "Manufacturer / OEM"

    def test_trader(self):
        assert business_type("We are a trading company and distributor.") == "Trader / Distributor"

    def test_supplier(self):
        assert business_type("Supplier of aluminum components.") == "Supplier"

    def test_unknown(self):
        assert business_type("We sell consulting services.") == "Unknown"


# ---------------------------------------------------------------------------
# build_analysis full payload
# ---------------------------------------------------------------------------
class TestBuildAnalysis:
    def test_returns_all_required_keys(self):
        text = "Aluminum die casting manufacturer for automotive EV."
        result = build_analysis(company="TestCo", country="USA", industry="Automotive", text=text)
        required_keys = [
            "company", "country", "industry", "business_type", "products",
            "materials", "manufacturing_process", "target_market",
            "casting_need_score", "cnc_need_score", "tooling_need_score",
            "buying_signal", "recommended_contact", "reason", "priority",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_priority_high_for_strong_lead(self):
        text = "Aluminum die casting manufacturer for automotive EV motor housing."
        result = build_analysis(text=text)
        assert result["priority"] == "HIGH"
        assert result["casting_need_score"] >= 80

    def test_priority_low_for_weak_lead(self):
        text = "We are a consulting firm."
        result = build_analysis(text=text)
        assert result["priority"] == "LOW"

    def test_buying_signal_in_result(self):
        text = "Looking for suppliers of aluminum die casting. We are a manufacturer."
        result = build_analysis(text=text)
        assert "HIGH" in result["buying_signal"]

    def test_materials_populated(self):
        text = "We use aluminum, magnesium, and ADC12 alloys."
        result = build_analysis(text=text)
        assert "aluminum" in result["materials"]
        assert "magnesium" in result["materials"]
