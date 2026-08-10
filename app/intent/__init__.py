"""Phase 16.1: Intent Event Foundation.

Storage + deterministic ingestion layer for :class:`SignalEvent`. Splits into:

  * :mod:`app.intent.repository` — thin, side-effect-free DB access.
  * :mod:`app.intent.service`    — deterministic dedup / upsert orchestration.

This package contains NO external API calls, NO scoring logic and NO changes to
lead / opportunity / contact scoring. It is the foundation that Phase 16.2
(source adapters) and Phase 16.4 (scoring redesign) will build on.
"""
