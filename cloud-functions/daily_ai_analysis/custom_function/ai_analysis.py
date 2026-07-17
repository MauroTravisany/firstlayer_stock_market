import hashlib
import json

from openai import OpenAI

from custom_function.bq_operations import row_to_json


TICKER_SCHEMA = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string"},
        "executive_summary": {"type": "string"},
        "internal_data_analysis": {"type": "string"},
        "external_context": {"type": "string"},
        "valuation_view": {"type": "string"},
        "quality_view": {"type": "string"},
        "momentum_view": {"type": "string"},
        "risk_view": {"type": "string"},
        "discrepancies": {"type": "string"},
        "opportunity": {"type": "string"},
        "decision_support": {"type": "string"},
        "confidence_score": {"type": "number"},
        "confidence_reason": {"type": "string"},
        "alert_summary": {"type": "string"},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "publisher": {"type": "string"},
                    "published_date": {"type": "string"},
                    "used_for": {"type": "string"},
                },
                "required": ["title", "url", "publisher", "published_date", "used_for"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "ticker",
        "executive_summary",
        "internal_data_analysis",
        "external_context",
        "valuation_view",
        "quality_view",
        "momentum_view",
        "risk_view",
        "discrepancies",
        "opportunity",
        "decision_support",
        "confidence_score",
        "confidence_reason",
        "alert_summary",
        "sources",
    ],
    "additionalProperties": False,
}


SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "alert_title": {"type": "string"},
        "portfolio_summary": {"type": "string"},
        "top_opportunities": {"type": "string"},
        "overvalued_summary": {"type": "string"},
        "risk_summary": {"type": "string"},
        "dashboard_summary": {"type": "string"},
        "alert_body": {"type": "string"},
    },
    "required": [
        "alert_title",
        "portfolio_summary",
        "top_opportunities",
        "overvalued_summary",
        "risk_summary",
        "dashboard_summary",
        "alert_body",
    ],
    "additionalProperties": False,
}


SYSTEM_PROMPT = """
Eres un analista financiero objetivo. No das recomendacion financiera personalizada.
Tu tarea es explicar datos de una cartera usando primero datos internos del sistema.
Los datos internos provienen de BigQuery y Yahoo Finance procesado por el proyecto.
Puedes usar busqueda web solo para contrastar contexto externo, eventos recientes,
riesgos o discrepancias. No reemplaces los numeros internos con datos externos.

Reglas obligatorias:
1. No inventes datos, fuentes, fechas ni URLs.
2. Separa hechos de interpretacion.
3. Si no encuentras fuentes externas confiables, dilo claramente.
4. Si una fuente externa contradice los datos internos, marca la discrepancia.
5. Prioriza valoracion, calidad financiera, momentum y riesgo.
6. Explica la conclusion de forma objetiva y accionable, sin decir "compra" como orden.
7. Devuelve solo JSON valido segun el schema.
"""


def _json_schema(name, schema):
    return {
        "format": {
            "type": "json_schema",
            "name": name,
            "schema": schema,
            "strict": True,
        }
    }


def _extract_json(response):
    text = getattr(response, "output_text", None)
    if text:
        return json.loads(text)

    chunks = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", None) in {"output_text", "text"}:
                chunks.append(getattr(content, "text", ""))
    return json.loads("".join(chunks))


def _input_hash(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()


def analyze_ticker(config, signal_row):
    if not config.get("openai_api_key"):
        raise RuntimeError("OPENAI_API_KEY secret is required to generate AI analysis")
    client = OpenAI(api_key=config["openai_api_key"])
    ticker = signal_row["ticker"]
    payload = {
        "internal_data": json.loads(row_to_json(signal_row)),
        "external_search_instructions": {
            "query_focus": [
                f"{ticker} latest earnings guidance margin revenue debt risk",
                f"{ticker} stock recent news valuation risk",
                f"{ticker} investor relations earnings results",
            ],
            "preferred_sources": [
                "company investor relations",
                "SEC filings",
                "Yahoo Finance",
                "Reuters",
                "Nasdaq",
                "MarketWatch",
            ],
        },
    }

    response = client.responses.create(
        model=config["openai_model"],
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Analiza este ticker con los datos internos y contrasta con fuentes externas. "
                    "Usa busqueda web para contexto reciente y cita las fuentes usadas dentro de sources. "
                    f"Payload JSON:\n{json.dumps(payload, ensure_ascii=True)}"
                ),
            },
        ],
        tools=[{"type": "web_search"}],
        text=_json_schema("ticker_analysis", TICKER_SCHEMA),
    )
    parsed = _extract_json(response)
    return parsed, _input_hash(payload)


def build_analysis_row(config, signal_row, parsed, input_hash):
    return {
        "analysis_date": signal_row["analysis_date"],
        "ticker": signal_row["ticker"],
        "signal": signal_row.get("signal"),
        "classification": signal_row.get("classification"),
        "final_score": signal_row.get("final_score"),
        "valuation_score": signal_row.get("valuation_score"),
        "quality_score": signal_row.get("quality_score"),
        "momentum_score": signal_row.get("momentum_score"),
        "risk_score": signal_row.get("risk_score"),
        "ai_summary": parsed.get("executive_summary"),
        "ai_analysis": parsed.get("internal_data_analysis"),
        "ai_risks": parsed.get("risk_view"),
        "ai_opportunity": parsed.get("opportunity"),
        "ai_decision_support": parsed.get("decision_support"),
        "external_sources_json": json.dumps(parsed.get("sources", []), ensure_ascii=True),
        "external_context_summary": parsed.get("external_context"),
        "data_discrepancies": parsed.get("discrepancies"),
        "confidence_score": parsed.get("confidence_score"),
        "confidence_reason": parsed.get("confidence_reason"),
        "model_name": config["openai_model"],
        "prompt_version": config["prompt_version"],
        "input_hash": input_hash,
        "raw_response_json": json.dumps(parsed, ensure_ascii=True),
    }


def build_error_analysis_row(config, signal_row, exc):
    payload = json.loads(row_to_json(signal_row))
    return {
        "analysis_date": signal_row["analysis_date"],
        "ticker": signal_row["ticker"],
        "signal": signal_row.get("signal"),
        "classification": signal_row.get("classification"),
        "final_score": signal_row.get("final_score"),
        "valuation_score": signal_row.get("valuation_score"),
        "quality_score": signal_row.get("quality_score"),
        "momentum_score": signal_row.get("momentum_score"),
        "risk_score": signal_row.get("risk_score"),
        "ai_summary": "ERROR_GENERANDO_ANALISIS",
        "ai_analysis": str(exc),
        "ai_risks": None,
        "ai_opportunity": None,
        "ai_decision_support": None,
        "external_sources_json": "[]",
        "external_context_summary": None,
        "data_discrepancies": None,
        "confidence_score": 0.0,
        "confidence_reason": "La llamada de IA fallo; revisar logs y credenciales.",
        "model_name": config["openai_model"],
        "prompt_version": config["prompt_version"],
        "input_hash": _input_hash(payload),
        "raw_response_json": json.dumps({"error": str(exc)}, ensure_ascii=True),
    }


def build_portfolio_summary(config, analysis_rows):
    if not config.get("openai_api_key"):
        raise RuntimeError("OPENAI_API_KEY secret is required to generate portfolio summary")
    client = OpenAI(api_key=config["openai_api_key"])
    compact_rows = [
        {
            "ticker": row["ticker"],
            "signal": row["signal"],
            "classification": row["classification"],
            "final_score": row["final_score"],
            "summary": row.get("ai_summary"),
            "risks": row.get("ai_risks"),
            "opportunity": row.get("ai_opportunity"),
            "confidence_score": row.get("confidence_score"),
        }
        for row in analysis_rows
    ]
    analysis_date = str(analysis_rows[0]["analysis_date"]) if analysis_rows else ""

    response = client.responses.create(
        model=config["openai_model"],
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Crea un resumen ejecutivo en espanol para dashboard y alerta Slack/Discord. "
                    "Debe separar oportunidades, sobrevaloradas y riesgos. "
                    "No des recomendacion financiera personalizada. "
                    f"analysis_date={analysis_date}\n"
                    f"analysis_rows={json.dumps(compact_rows, ensure_ascii=True)}"
                ),
            },
        ],
        text=_json_schema("portfolio_summary", SUMMARY_SCHEMA),
    )
    return _extract_json(response)
