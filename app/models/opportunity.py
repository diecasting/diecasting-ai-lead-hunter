"""Sales Pipeline Opportunity models (Phase 11).

An :class:`Opportunity` is a *deal-level* entity that sits on top of the
existing lead funnel (``CompanyLead.lead_status``). It represents a concrete
revenue possibility with a stage, an amount, a win probability and an expected
close date, and can be traced back to the reply / RFQ that spawned it.

This is an **extension, not a CRM rewrite**: it reuses ``CompanyLead``,
``Contact``, ``ReplyAnalysis`` and ``ReplyRFQExtraction`` as foreign keys and
adds a separate ``OpportunityStageHistory`` audit table (mirroring the
``OutreachEvent`` timeline pattern) so stage transitions are fully traceable.

All foreign keys are ``SET NULL`` so deleting an underlying lead / contact /
reply / RFQ never orphans an opportunity — the deal keeps its descriptive
fields (amount, stage, probability) for pipeline analytics.
"""
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Stage vocabulary (deal-level funnel — distinct from CompanyLead.lead_status)
# ---------------------------------------------------------------------------
OPP_STAGE_PROSPECTING = "prospecting"
OPP_STAGE_QUALIFICATION = "qualification"
OPP_STAGE_PROPOSAL = "proposal"
OPP_STAGE_NEGOTIATION = "negotiation"
OPP_STAGE_WON = "won"
OPP_STAGE_LOST = "lost"

OPP_STAGES = (
    OPP_STAGE_PROSPECTING,
    OPP_STAGE_QUALIFICATION,
    OPP_STAGE_PROPOSAL,
    OPP_STAGE_NEGOTIATION,
    OPP_STAGE_WON,
    OPP_STAGE_LOST,
)

OPP_STAGE_DEFAULT = OPP_STAGE_PROSPECTING

# Open (still in play) vs terminal stages.
OPP_OPEN_STAGES = (
    OPP_STAGE_PROSPECTING,
    OPP_STAGE_QUALIFICATION,
    OPP_STAGE_PROPOSAL,
    OPP_STAGE_NEGOTIATION,
)
OPP_WON_STAGE = OPP_STAGE_WON
OPP_LOST_STAGE = OPP_STAGE_LOST

# Deterministic baseline win-probability per stage (0-100). Used whenever the
# probability is not set explicitly or enhanced by AI.
STAGE_PROBABILITY = {
    OPP_STAGE_PROSPECTING: 10,
    OPP_STAGE_QUALIFICATION: 25,
    OPP_STAGE_PROPOSAL: 50,
    OPP_STAGE_NEGOTIATION: 75,
    OPP_STAGE_WON: 100,
    OPP_STAGE_LOST: 0,
}


def default_probability(stage: str) -> int:
    """Deterministic baseline probability for a stage (falls back to 0)."""
    return STAGE_PROBABILITY.get(stage, 0)


def is_open(stage: str) -> bool:
    return stage in OPP_OPEN_STAGES


# ---------------------------------------------------------------------------
# Priority vocabulary (mirrors the CRM / campaign / task priority labels)
# ---------------------------------------------------------------------------
OPP_PRIORITY_HIGH = "high"
OPP_PRIORITY_MEDIUM = "medium"
OPP_PRIORITY_LOW = "low"

OPP_PRIORITIES = (
    OPP_PRIORITY_HIGH,
    OPP_PRIORITY_MEDIUM,
    OPP_PRIORITY_LOW,
)

OPP_CURRENCY_DEFAULT = "USD"


class Opportunity(Base):
    """A revenue opportunity (deal) tracked through a sales pipeline stage."""

    __tablename__ = "opportunities"

    id = Column(Integer, primary_key=True, index=True)

    # Ownership (all nullable so history survives downstream deletions).
    company_id = Column(
        Integer,
        ForeignKey("company_leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contact_id = Column(
        Integer,
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reply_id = Column(
        Integer,
        ForeignKey("reply_analyses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    rfq_id = Column(
        Integer,
        ForeignKey("reply_rfq_extractions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Phase 15.4.3: attribution bridge to the Conversion Intelligence signal
    # that (may have) triggered this deal. Nullable + SET NULL so deleting the
    # underlying signal never orphans the opportunity.
    conversion_signal_id = Column(
        Integer,
        ForeignKey("conversion_signals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Deal attributes.
    stage = Column(
        String(20), nullable=False, default=OPP_STAGE_DEFAULT,
        server_default=OPP_STAGE_DEFAULT, index=True,
    )
    amount = Column(Float, nullable=True)
    currency = Column(
        String(3), nullable=False, default=OPP_CURRENCY_DEFAULT,
        server_default=OPP_CURRENCY_DEFAULT,
    )
    probability = Column(Integer, nullable=True, index=True)
    expected_close_date = Column(Date, nullable=True)
    actual_close_date = Column(Date, nullable=True)

    # Phase 15.4.3: Conversion Intelligence snapshot copied at creation time and
    # an optional AI-enhanced probability. ``probability_source`` distinguishes a
    # human-set probability ("manual") from one enhanced by the conversion signal
    # ("conversion"); ``ai_probability`` always records the AI suggestion for
    # reference without clobbering a manual call.
    ai_temperature_score = Column(Integer, nullable=True)
    ai_intent_score = Column(Integer, nullable=True)
    ai_probability = Column(Integer, nullable=True)
    probability_source = Column(String(20), nullable=True)

    # Sales routing / metadata.
    priority = Column(
        String(20), nullable=False, default=OPP_PRIORITY_MEDIUM,
        server_default=OPP_PRIORITY_MEDIUM, index=True,
    )
    owner = Column(String(120), nullable=True)
    notes = Column(Text, nullable=True)

    used_ai = Column(Boolean, nullable=False, default=False, server_default="0")

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=True
    )

    company = relationship("CompanyLead", backref="opportunities", lazy="selectin")
    contact = relationship("Contact", backref="opportunities", lazy="selectin")
    reply = relationship("ReplyAnalysis", backref="opportunities", lazy="selectin")
    rfq = relationship("ReplyRFQExtraction", backref="opportunities", lazy="selectin")
    conv_signal = relationship(
        "ConversionSignal", backref="opportunities", lazy="selectin"
    )
    stage_history = relationship(
        "OpportunityStageHistory",
        backref="opportunity",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="OpportunityStageHistory.changed_at",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Opportunity id={self.id} stage={self.stage!r} "
            f"amount={self.amount!r} probability={self.probability!r}>"
        )


class OpportunityStageHistory(Base):
    """Append-only audit log of stage transitions for an Opportunity.

    Mirrors the ``OutreachEvent`` timeline used for replies: every transition
    (including creation) appends a row so time-in-stage / velocity analytics are
    possible without mutating the opportunity row itself.
    """

    __tablename__ = "opportunity_stage_history"

    id = Column(Integer, primary_key=True, index=True)
    opportunity_id = Column(
        Integer,
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_stage = Column(String(20), nullable=True)
    to_stage = Column(String(20), nullable=True)
    changed_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    note = Column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<OpportunityStageHistory id={self.id} "
            f"opp={self.opportunity_id} {self.from_stage} -> {self.to_stage}>"
        )


def create_opportunity_from_rfq(
    db,
    lead,
    analysis,
    rfq_extraction,
    *,
    contact_id: Optional[int] = None,
    stage: str = OPP_STAGE_QUALIFICATION,
    use_ai: bool = True,
    conversion_signal=None,
) -> "Opportunity":
    """Create an :class:`Opportunity` from a classified ``rfq_request`` reply.

    Reuses the original reply text + the structured :class:`ReplyRFQExtraction`
    to score the deal (deterministic baseline, optionally upgraded by AI), then
    persists the opportunity and an opening :class:`OpportunityStageHistory`
    row. The scorer is imported lazily to avoid a circular import with
    ``app.opportunity_scoring``.

    Phase 15.4.3: if an existing :class:`ConversionSignal` is supplied (the
    signal that triggered / accompanied this reply), it is attached via
    ``conversion_signal_id`` and its ``temperature_score`` / ``intent_score`` are
    copied onto ``ai_temperature_score`` / ``ai_intent_score`` for attribution.
    The signal is **never** created here — the caller passes an already-persisted
    one (or ``None``).

    Returns the created :class:`Opportunity`. Does **not** touch the CRM lead
    status — that is owned by the Phase 6 / 10 action engine.
    """
    from app.opportunity_scoring import score_opportunity

    rfq_fields = {
        "product": rfq_extraction.product,
        "quantity": rfq_extraction.quantity,
        "material": rfq_extraction.material,
        "process": rfq_extraction.process,
        "deadline": rfq_extraction.deadline,
        "requirements": rfq_extraction.requirements,
    }
    score, used_ai = score_opportunity(
        stage,
        reply_text=analysis.reply_text,
        rfq_fields=rfq_fields,
        company_priority=getattr(lead, "sales_priority", None),
        company_name=getattr(lead, "name", None),
        use_ai=use_ai,
    )

    # Phase 15.4.3: copy attribution from the (optional) existing signal.
    signal_id = getattr(conversion_signal, "id", None)
    ai_temperature = getattr(conversion_signal, "temperature_score", None)
    ai_intent = getattr(conversion_signal, "intent_score", None)

    opp = Opportunity(
        company_id=lead.id,
        contact_id=contact_id,
        reply_id=analysis.id,
        rfq_id=rfq_extraction.id,
        conversion_signal_id=signal_id,
        stage=stage,
        amount=score.get("amount"),
        currency=(score.get("currency") or OPP_CURRENCY_DEFAULT),
        probability=score.get("probability"),
        priority=score.get("priority") or OPP_PRIORITY_MEDIUM,
        expected_close_date=score.get("expected_close_date"),
        notes=score.get("notes")
        or f"Auto-created from RFQ reply (analysis #{analysis.id})",
        used_ai=bool(used_ai),
        ai_temperature_score=ai_temperature,
        ai_intent_score=ai_intent,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)

    history = OpportunityStageHistory(
        opportunity_id=opp.id,
        from_stage=None,
        to_stage=stage,
        changed_at=datetime.now(timezone.utc),
        note="Created from rfq_request reply",
    )
    db.add(history)
    db.commit()
    db.refresh(opp)
    return opp


def apply_stage_change(
    db,
    opportunity: "Opportunity",
    new_stage: str,
    *,
    note: Optional[str] = None,
) -> "Opportunity":
    """Transition ``opportunity`` to ``new_stage``, appending a history row.

    Records ``actual_close_date`` when entering a terminal stage (won / lost)
    and leaves ``probability`` under the caller's control (it is *not*
    auto-overwritten here, so a sales rep's manual judgment is preserved).
    """
    from_stage = opportunity.stage
    if from_stage == new_stage:
        return opportunity

    opportunity.stage = new_stage
    opportunity.updated_at = datetime.now(timezone.utc)
    if new_stage in (OPP_WON_STAGE, OPP_LOST_STAGE) and opportunity.actual_close_date is None:
        opportunity.actual_close_date = date.today()
    db.add(opportunity)
    db.commit()

    history = OpportunityStageHistory(
        opportunity_id=opportunity.id,
        from_stage=from_stage,
        to_stage=new_stage,
        changed_at=datetime.now(timezone.utc),
        note=note or f"Stage change {from_stage} -> {new_stage}",
    )
    db.add(history)
    db.commit()
    db.refresh(opportunity)
    return opportunity


# ---------------------------------------------------------------------------
# Phase 15.4.3: Conversion Intelligence probability enhancement
# ---------------------------------------------------------------------------
PROBABILITY_SOURCE_MANUAL = "manual"
PROBABILITY_SOURCE_CONVERSION = "conversion"


def _ai_probability_from_signal(signal) -> Optional[int]:
    """Deterministic AI probability (0..100) synthesised from a signal.

    Pure synthesis: temperature carries most of the weight, intent score nudges
    it (positive intent raises, negative intent lowers, clamped). No LLM, no
    network. Returns ``None`` when the signal or its temperature is missing.
    """
    if signal is None:
        return None
    temp = getattr(signal, "temperature_score", None)
    if temp is None:
        return None
    intent = getattr(signal, "intent_score", None) or 0
    # Intent contributes at most +/-20 points (intent_score is -100..100).
    intent_nudge = max(-20, min(20, intent // 5))
    return max(0, min(100, temp + intent_nudge))


def enhance_opportunity_probability(db, opportunity, signal=None) -> "Opportunity":
    """Enhance an opportunity's probability using its conversion signal.

    Computes the AI probability via :func:`_ai_probability_from_signal` and
    records it on ``ai_probability`` for reference. If the opportunity already
    carries a *manual* probability (``probability_source == 'manual'``), the
    existing ``probability`` is preserved and only ``ai_probability`` is updated.
    Otherwise ``probability`` is overwritten with the AI value and
    ``probability_source`` is set to ``'conversion'``.

    Does NOT create ConversionSignals, Opportunities, Quotes, SalesTasks, or
    touch the outreach send path. The signal is resolved from
    ``opportunity.conversion_signal_id`` when not passed explicitly.
    """
    if signal is None and opportunity.conversion_signal_id is not None:
        from app.models.conversion_signal import ConversionSignal

        signal = (
            db.query(ConversionSignal)
            .filter(ConversionSignal.id == opportunity.conversion_signal_id)
            .first()
        )

    ai_prob = _ai_probability_from_signal(signal)
    # Always record the AI suggestion.
    opportunity.ai_probability = ai_prob

    if ai_prob is not None and opportunity.probability_source != PROBABILITY_SOURCE_MANUAL:
        opportunity.probability = ai_prob
        opportunity.probability_source = PROBABILITY_SOURCE_CONVERSION

    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)
    return opportunity
