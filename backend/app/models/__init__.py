"""
Academix AI — Pydantic schemas.

Import from the specific module (`app.models.rag`, `app.models.classroom`, …)
rather than relying on a star re-export here: several modules define same-named
symbols (ExamType, SourceType, …) and a wildcard would silently shadow them.
"""
