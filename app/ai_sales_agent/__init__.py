"""AI Sales Agent (Phase 9).

Brings together the pieces needed to run an autonomous-ish B2B sales copilot on
top of the existing infrastructure:

  * ``llm``            — the single, best-effort LLM provider abstraction
  * ``prompts``        — role-based (persona) sales prompts
  * ``research``       — company research summary generator
  * ``personalization``— AI email personalization engine (reuses the Outreach
                         Engine's template generator as the deterministic base)
  * ``quality``        — deterministic email quality scoring
  * ``crud`` / ``service`` — draft persistence + orchestration
"""
