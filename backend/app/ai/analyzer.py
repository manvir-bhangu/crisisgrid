import json
import logging

from sqlalchemy import text

from app.ai.duplicates import find_duplicates
from app.ai.fallback_rules import protocol_floor, rule_assessment
from app.ai.provider import call_llm
from app.ai.schemas import SEV_ORDER
from app.core.config import settings
from app.db.session import engine
from app.realtime.events import publish

log = logging.getLogger("crisisgrid.ai")


def analyze(incident_id: int) -> dict | None:
    with engine.connect() as conn:
        inc = conn.execute(text("SELECT raw_text FROM incidents WHERE id = :i"),
                           {"i": incident_id}).mappings().first()
    if not inc:
        return None
    report = inc["raw_text"]

    rule = rule_assessment(report)
    floor = protocol_floor(report)
    result, source, meta, error = rule, "rules", {}, None

    if settings.ai_enabled and settings.gemini_api_key:
        try:
            result, meta = call_llm(report)
            source = "llm"
        except Exception as exc:                 # any LLM failure degrades to rules
            error = repr(exc)[:300]
            log.warning("LLM failed for incident %s, using rules: %s", incident_id, error)
            result = rule

    floor_applied = SEV_ORDER[result.severity] < SEV_ORDER[floor]
    severity = floor if floor_applied else result.severity

    with engine.begin() as conn:
        dupes = find_duplicates(conn, incident_id, report)
        row = conn.execute(text("""
            INSERT INTO ai_assessments
              (incident_id, source, category, severity, confidence, injuries, trapped,
               location_clues, reasoning, floor_applied, rule_category, rule_severity,
               provider, model, tokens, latency_ms, cached, error, duplicates)
            VALUES (:i, :src, :cat, :sev, :conf, :inj, :trap, CAST(:clues AS jsonb), :why,
                    :floor, :rc, :rs, :prov, :model, :tok, :lat, :cached, :err, CAST(:dup AS jsonb))
            RETURNING id"""), {
            "i": incident_id, "src": source, "cat": result.category, "sev": severity,
            "conf": result.confidence, "inj": result.injuries, "trap": result.trapped,
            "clues": json.dumps(result.location_clues), "why": result.reasoning,
            "floor": floor_applied, "rc": rule.category, "rs": rule.severity,
            "prov": "gemini" if source == "llm" else None,
            "model": settings.gemini_model if source == "llm" else None,
            "tok": meta.get("tokens"), "lat": meta.get("latency_ms"),
            "cached": bool(meta.get("cached")), "err": error, "dup": json.dumps(dupes)}).first()

    summary = {"incident_id": incident_id, "assessment_id": row[0], "source": source,
               "category": result.category, "severity": severity, "duplicates": len(dupes)}
    publish("ai_assessment_ready", summary)
    return summary