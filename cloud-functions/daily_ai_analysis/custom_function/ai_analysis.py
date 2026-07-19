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
        "sell_thesis": {"type": "string"},
        "sell_reasons": {"type": "string"},
        "sell_price_view": {"type": "string"},
        "sell_decision_support": {"type": "string"},
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
        "sell_thesis",
        "sell_reasons",
        "sell_price_view",
        "sell_decision_support",
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
6. Explica la conclusion de forma objetiva y accionable, sin decir "compra" o "vende" como orden.
7. Responde siempre en espanol en todos los campos narrativos del JSON.
8. Si las fuentes externas estan en ingles, resume su contenido en espanol.
9. confidence_score debe ser un numero entre 0.0 y 1.0, no porcentaje.
10. Devuelve solo JSON valido segun el schema.
11. Si sell_signal indica VENTA_CLARA o VENTA_PARCIAL_OBSERVAR, evalua si la empresa parece cara con los multiplos disponibles, calidad, momentum, riesgo y contexto externo.
12. En sell_price_view explica el precio o zona sugerida para evaluar venta usando suggested_sell_price, last_close y los multiplos internos. No inventes precio objetivo externo.
13. Trata signal y classification como una preseleccion cuantitativa, no como conclusion definitiva.
14. Si signal indica COMPRAR_OBSERVAR pero PE > 35, forward PE > 28, price_to_sales > 6 o EV/EBITDA > 22, advierte que la valoracion contradice una oportunidad clara y reduce confidence_score salvo que existan razones extraordinarias.
15. Una empresa de alta calidad cerca de multiplos exigentes debe describirse como "calidad a precio exigente" o "mantener/observar", no como barata.
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


def _missing_ratio_fields(signal_row):
    ratio_fields = [
        "pe_ratio",
        "forward_pe",
        "price_to_sales",
        "ev_to_ebitda",
        "roe",
        "profit_margin",
        "operating_margin",
        "debt_to_equity",
        "current_ratio",
        "free_cash_flow",
    ]
    return [field for field in ratio_fields if signal_row.get(field) is None]


def build_ticker_payload(signal_row):
    ticker = signal_row["ticker"]
    missing_ratios = _missing_ratio_fields(signal_row)
    return {
        "internal_data": json.loads(row_to_json(signal_row)),
        "missing_internal_ratios": missing_ratios,
        "external_search_instructions": {
            "query_focus": [
                f"{ticker} latest earnings guidance margin revenue debt risk",
                f"{ticker} stock recent news valuation risk",
                f"{ticker} valuation multiples overvalued sell risk",
                f"{ticker} PE forward PE price sales EV EBITDA ROE debt equity free cash flow",
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


def ticker_input_hash(signal_row):
    return _input_hash(build_ticker_payload(signal_row))


def analyze_ticker(config, signal_row):
    if not config.get("openai_api_key"):
        raise RuntimeError("OPENAI_API_KEY secret is required to generate AI analysis")
    client = OpenAI(api_key=config["openai_api_key"])
    payload = build_ticker_payload(signal_row)

    response = client.responses.create(
        model=config["openai_model"],
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Analiza este ticker con los datos internos y contrasta con fuentes externas. "
                    "Incluye una tesis de venta objetiva cuando los datos sugieran sobrevaloracion, deterioro o riesgo elevado. "
                    "Evalua los ratios disponibles frente a umbrales razonables: PE, forward PE, price to sales, EV/EBITDA, ROE, margenes, deuda, liquidez, FCF, momentum y volatilidad. "
                    "No confirmes una oportunidad clara solo porque signal lo diga; valida que los multiplos sean razonables y que no exista una contradiccion de valoracion. "
                    "Si la accion tiene calidad alta pero multiplos caros, explica que no es una compra clara y que requiere mejor precio o mayor margen de seguridad. "
                    "Si missing_internal_ratios no esta vacio, busca esos ratios faltantes en fuentes externas confiables y usalos solo como contraste externo. "
                    "Cuando uses un ratio externo, indica fuente, fecha aproximada si esta disponible, y advierte que no reemplaza al dato interno de BigQuery. "
                    "Si no hay caso de venta, dilo claramente y explica que condiciones activarian una revision de venta. "
                    "Usa busqueda web para contexto reciente y cita las fuentes usadas dentro de sources. "
                    "Todos los textos explicativos deben estar en espanol. "
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
        "sell_score": signal_row.get("sell_score"),
        "sell_signal": signal_row.get("sell_signal"),
        "suggested_sell_price": signal_row.get("suggested_sell_price"),
        "ai_sell_thesis": parsed.get("sell_thesis"),
        "ai_sell_reasons": parsed.get("sell_reasons"),
        "ai_sell_price_view": parsed.get("sell_price_view"),
        "ai_sell_decision_support": parsed.get("sell_decision_support"),
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
        "sell_score": signal_row.get("sell_score"),
        "sell_signal": signal_row.get("sell_signal"),
        "suggested_sell_price": signal_row.get("suggested_sell_price"),
        "ai_sell_thesis": None,
        "ai_sell_reasons": None,
        "ai_sell_price_view": None,
        "ai_sell_decision_support": None,
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
            "sell_score": row.get("sell_score"),
            "sell_signal": row.get("sell_signal"),
            "suggested_sell_price": row.get("suggested_sell_price"),
            "sell_thesis": row.get("ai_sell_thesis"),
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
                    "Debe separar oportunidades de compra, posiciones caras con posible venta y riesgos. "
                    "No des recomendacion financiera personalizada. "
                    "Todos los campos de texto deben estar escritos en espanol. "
                    f"analysis_date={analysis_date}\n"
                    f"analysis_rows={json.dumps(compact_rows, ensure_ascii=True)}"
                ),
            },
        ],
        text=_json_schema("portfolio_summary", SUMMARY_SCHEMA),
    )
    return _extract_json(response)
