"""Tests for email template selection and rendering."""
from app.outreach.email_generator import (
    _INDUSTRY_TEMPLATE,
    _TEMPLATE_DIR,
    _detect_industry,
    _extract_section,
    _fill_template,
    _load_template,
)


class TestIndustryDetection:
    """Industry string → template filename mapping."""

    def test_automotive(self):
        assert _detect_industry("automotive") == "automotive.md"
        assert _detect_industry("Automotive Parts") == "automotive.md"

    def test_ev(self):
        assert _detect_industry("electric vehicle") == "ev.md"
        assert _detect_industry("EV manufacturer") == "ev.md"
        assert _detect_industry("battery") == "ev.md"
        assert _detect_industry("motor housing") == "ev.md"

    def test_hydraulic(self):
        assert _detect_industry("hydraulic") == "hydraulic.md"
        assert _detect_industry("hydraulic systems") == "hydraulic.md"

    def test_pump(self):
        assert _detect_industry("pump") == "pump.md"
        assert _detect_industry("water pump") == "pump.md"

    def test_gearbox(self):
        assert _detect_industry("gearbox") == "gearbox.md"
        assert _detect_industry("transmission") == "gearbox.md"

    def test_industrial(self):
        assert _detect_industry("industrial equipment") == "industrial_equipment.md"
        assert _detect_industry("robotics") == "industrial_equipment.md"
        assert _detect_industry("aerospace") == "industrial_equipment.md"

    def test_cnc(self):
        assert _detect_industry("cnc machining") == "cnc.md"
        assert _detect_industry("CNC") == "cnc.md"
        assert _detect_industry("machining") == "cnc.md"

    def test_tooling(self):
        assert _detect_industry("tooling") == "tooling.md"
        assert _detect_industry("mold") == "tooling.md"

    def test_unknown_fallback(self):
        assert _detect_industry("") == "industrial_equipment.md"
        assert _detect_industry("random sector") == "industrial_equipment.md"


class TestTemplateLoading:
    """All 8 templates exist and contain required sections."""

    REQUIRED_SECTIONS = ["Subject", "Key Capabilities to Highlight", "Value Proposition", "Suggested Call to Action"]

    def test_all_templates_exist(self):
        for key, filename in _INDUSTRY_TEMPLATE.items():
            path = _TEMPLATE_DIR / filename
            assert path.exists(), f"Template {filename} missing for {key}"

    def test_all_templates_have_sections(self):
        seen = set()
        for filename in _INDUSTRY_TEMPLATE.values():
            if filename in seen:
                continue
            seen.add(filename)
            md = _load_template(filename)
            for section in self.REQUIRED_SECTIONS:
                content = _extract_section(md, section)
                assert content, f"Section '{section}' empty in {filename}"

    def test_templates_contain_company_placeholder(self):
        """Every template should use {company} for personalisation."""
        seen = set()
        for filename in _INDUSTRY_TEMPLATE.values():
            if filename in seen:
                continue
            seen.add(filename)
            md = _load_template(filename)
            assert "{company}" in md, f"Missing {{company}} placeholder in {filename}"

    def test_industrial_equipment_fallback_loads(self):
        md = _load_template("industrial_equipment.md")
        assert len(md) > 100

    def test_nonexistent_template_falls_back(self):
        md = _load_template("nonexistent.md")
        assert len(md) > 100


class TestTemplateRendering:
    """Variable substitution in templates."""

    def test_subject_substitution(self):
        md = _load_template("automotive.md")
        result = _fill_template(md, {"company": "ACME Corp"})
        assert "ACME Corp" in result["subject"]

    def test_body_contains_capabilities(self):
        md = _load_template("cnc.md")
        result = _fill_template(md, {"company": "TestCo"})
        assert len(result["body"]) > 50

    def test_opening_is_personalised(self):
        md = _load_template("ev.md")
        result = _fill_template(md, {"company": "EV Motors Ltd"})
        assert "EV Motors Ltd" in result["opening"]

    def test_cta_not_empty(self):
        md = _load_template("tooling.md")
        result = _fill_template(md, {"company": "MoldMaker Inc"})
        assert len(result["call_to_action"]) > 10

    def test_missing_variable_not_error(self):
        md = _load_template("pump.md")
        result = _fill_template(md, {})  # no company variable
        assert result["subject"]  # should still render
        assert result["body"]

    def test_rendered_has_all_keys(self):
        md = _load_template("gearbox.md")
        result = _fill_template(md, {"company": "GearWorks"})
        for key in ("subject", "opening", "body", "call_to_action"):
            assert key in result
            assert result[key]
