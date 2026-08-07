"""Email Discovery & Verification Engine (Phase 8).

Sub-modules
-----------
* ``extractor``   — website e-mail crawler (injectable fetcher).
* ``patterns``    — e-mail pattern inference + role / personal classification.
* ``ranking``     — contact e-mail prioritisation.
* ``verification``— deliverability pipeline (syntax / disposable / MX / SMTP /
                    catch-all), reusing the outreach verification primitives.
* ``crud``        — thin persistence helpers for :class:`EmailAddress`.
* ``service``     — orchestration used by the API layer.
"""
