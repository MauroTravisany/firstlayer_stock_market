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
        "technical_view": {"type": "string"},
        "fair_value_view": {"type": "string"},
        "data_quality_view": {"type": "string"},
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
        "ai_valuation_opinion": {"type": "string", "enum": ["BARATA", "PRECIO_JUSTO", "CARA", "DATOS_INSUFICIENTES"]},
        "ai_signal_agreement": {"type": "string", "enum": ["CONFIRMA_MODELO", "CONTRADICE_MODELO", "NEUTRAL"]},
        "ai_final_alert_action": {"type": "string", "enum": ["ENVIAR_COMPRA", "ENVIAR_VENTA", "NO_ENVIAR"]},
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
        "technical_view",
        "fair_value_view",
        "data_quality_view",
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
        "ai_valuation_opinion",
        "ai_signal_agreement",
        "ai_final_alert_action",
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
        "discord_summary": {"type": "string"},
        "full_report": {"type": "string"},
    },
    "required": [
        "alert_title",
        "portfolio_summary",
        "top_opportunities",
        "overvalued_summary",
        "risk_summary",
        "dashboard_summary",
        "alert_body",
        "discord_summary",
        "full_report",
    ],
    "additionalProperties": False,
}


WEEKLY_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "alert_title": {"type": "string"},
        "weekly_summary": {"type": "string"},
        "important_moves": {"type": "string"},
        "state_changes": {"type": "string"},
        "risk_changes": {"type": "string"},
        "trend_changes": {"type": "string"},
        "watch_next_week": {"type": "string"},
        "alert_body": {"type": "string"},
        "discord_summary": {"type": "string"},
        "full_report": {"type": "string"},
    },
    "required": [
        "alert_title",
        "weekly_summary",
        "important_moves",
        "state_changes",
        "risk_changes",
        "trend_changes",
        "watch_next_week",
        "alert_body",
        "discord_summary",
        "full_report",
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
16. ai_valuation_opinion debe ser tu conclusion final independiente: BARATA, PRECIO_JUSTO, CARA o DATOS_INSUFICIENTES.
17. ai_signal_agreement debe indicar si confirmas o contradices la senal cuantitativa.
18. ai_final_alert_action solo debe ser ENVIAR_COMPRA cuando la tesis de compra sea clara, los multiplos sean razonables vs peers y no existan contradicciones relevantes.
19. Usa fair_value_estimate, conservative_fair_value, margin_of_safety_pct, suggested_buy_price y suggested_sell_price para explicar precio justo y margen de seguridad. No los presentes como verdad exacta.
20. Usa technical_trend, technical_score, return_20d, return_60d, return_120d y medias moviles como confirmacion secundaria. El analisis tecnico no debe superar a la valoracion fundamental.
21. Usa missing_data_impact y data_quality_score para indicar si la conclusion es confiable. Si el impacto es ALTO, no envies una alerta clara.
22. Escribe para un inversionista no tecnico: primero interpreta en lenguaje natural y despues menciona los ratios que respaldan la conclusion.
23. Cada vez que menciones PE, forward PE, P/S, P/B, EV/EBITDA, ROE, margen, deuda o flujo de caja, explica en una frase que significa para decidir compra, observacion o venta.
24. Evita frases cargadas de jerga como "multiples exigentes" sin explicacion. Prefiere "el mercado esta pagando caro por cada dolar de ventas" o "el precio ya descuenta mucho crecimiento".
25. Para compra, explica claramente: por que podria estar barata, que debe mejorar o mantenerse, que precio/zona haria mas atractiva la entrada y que riesgos invalidarian la tesis.
26. Para venta, explica claramente: por que podria estar cara, si el riesgo es precio alto, deterioro del negocio o perdida de tendencia, que ratio lo muestra y que condicion permitiria mantenerla.
27. En opportunity y decision_support incluye una mini explicacion de precio: precio actual, suggested_buy_price, cuanto faltaria bajar en porcentaje si el precio actual esta arriba de suggested_buy_price, y margen de seguridad.
28. En sell_thesis, sell_reasons y sell_decision_support incluye una mini explicacion de precio: precio actual, suggested_sell_price, si ya esta en zona de revision o cuanto faltaria para llegar.
29. No pongas solo "PE 20" o "P/S 5"; escribe "PE esta en 20: significa que el mercado paga 20 veces las ganancias actuales; es razonable/caro/barato frente a la referencia".
30. Mantén el lenguaje simple pero completo: la persona debe entender que significa cada ratio sin estudiar finanzas.
31. Si asset_type es CRYPTO, no uses PE, P/S, EV/EBITDA, ROE, deuda ni flujo de caja como criterios. Explica que no aplican porque BTC/ETH no son empresas.
32. Para CRYPTO usa precio, retorno 20/60/120 dias, SMA 20/60/120, high_252d, low_252d, volatilidad, crypto_regime, eth_btc_ratio y eth_vs_btc_60d.
33. Si crypto_regime es BTC_DOMINANTE, explica que Bitcoin lidera y que las altcoins aun no muestran fuerza relativa clara. Si es ALTCOIN_ROTATION, explica que ETH supera a BTC y podria haber mayor apetito por altcoins. Si es CRYPTO_DEBIL, enfatiza riesgo.
34. Para BTC/ETH usa ai_valuation_opinion como lectura relativa: BARATA si esta castigado pero recuperando tendencia, PRECIO_JUSTO si no hay ventaja clara, CARA si esta sobreextendido, DATOS_INSUFICIENTES si faltan precios.
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
        "price_to_book",
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
                    "Usa lenguaje funcional y natural: una persona debe entender la conclusion aunque no conozca los ratios. "
                    "Primero di la lectura simple, luego muestra los ratios como evidencia y explica que significa cada uno. "
                    "Incluye precio actual, precio tentativo de compra/venta y porcentaje aproximado que falta para llegar a esa zona cuando existan los datos. "
                    "Incluye una tesis de venta objetiva cuando los datos sugieran sobrevaloracion, deterioro o riesgo elevado. "
                    "Evalua los ratios disponibles segun valuation_model y primary_metric; no apliques la misma lectura a bancos, software, semiconductores, consumo defensivo, restaurantes, crypto-financials o ETFs. "
                    "Usa PE, forward PE, price to sales, price to book, EV/EBITDA, ROE, margenes, deuda, liquidez, FCF, momentum y volatilidad con la importancia que corresponda a la industria. "
                    "Evalua precio justo, precio objetivo conservador y margen de seguridad usando los campos internos fair_value_estimate, conservative_fair_value, margin_of_safety_pct, suggested_buy_price y suggested_sell_price. "
                    "Usa adaptive_forward_pe_limit, adaptive_price_to_sales_limit, adaptive_ev_to_ebitda_limit, adaptive_price_to_book_limit y buy_multiple_guardrail_pass para saber si los multiplos pasan los limites dinamicos del modelo/peers. "
                    "Incluye analisis tecnico semanal/mensual como confirmacion secundaria usando return_20d, return_60d, return_120d, sma_20, sma_60, sma_120, high_252d, low_252d y technical_trend. "
                    "Explica el impacto de datos faltantes usando missing_data_impact y data_quality_score. "
                    "No confirmes una oportunidad clara solo porque signal lo diga; valida que los multiplos sean razonables y que no exista una contradiccion de valoracion. "
                    "Si la accion tiene calidad alta pero multiplos caros, explica que no es una compra clara y que requiere mejor precio o mayor margen de seguridad. "
                    "Usa peer_group, peer_valuation_label, peer_relative_score y percentiles relativos para comparar contra homologos. "
                    "Si asset_type es ETF, evalualo como instrumento de seguimiento/allocacion y no como empresa con fundamentales corporativos. "
                    "Si asset_type es CRYPTO, evalualo como criptoactivo: no tiene ganancias, ventas, EBITDA ni balance corporativo comparable. "
                    "Para CRYPTO enfocate en tendencia, drawdown contra maximo anual, recuperacion sobre medias moviles, volatilidad, regimen BTC/ETH, eth_btc_ratio y eth_vs_btc_60d. "
                    "Explica la dominancia: BTC_DOMINANTE significa que BTC lidera; ALTCOIN_ROTATION significa que ETH gana fuerza relativa y puede anticipar mayor apetito por altcoins; CRYPTO_DEBIL significa debilidad amplia. "
                    "Si peer_count es menor a 3, baja la confianza y declara que la comparacion relativa es limitada. "
                    "Si missing_internal_ratios no esta vacio, busca esos ratios faltantes en fuentes externas confiables y usalos solo como contraste externo. "
                    "Cuando uses un ratio externo, indica fuente, fecha aproximada si esta disponible, y advierte que no reemplaza al dato interno de BigQuery. "
                    "Si no hay caso de venta, dilo claramente y explica que condiciones activarian una revision de venta. "
                    "Evita textos demasiado tecnicos en executive_summary, opportunity, sell_thesis, sell_reasons, decision_support y sell_decision_support. "
                    "En esos campos, traduce los ratios a implicancias practicas: barato/caro frente a ganancias, ventas, flujo operativo, deuda, margen, calidad y tendencia. "
                    "No escribas listas de ratios sin interpretacion. Cada ratio relevante debe tener valor actual y significado practico en una frase breve. "
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
        "ai_technical_view": parsed.get("technical_view"),
        "ai_fair_value_view": parsed.get("fair_value_view"),
        "ai_data_quality_view": parsed.get("data_quality_view"),
        "ai_opportunity": parsed.get("opportunity"),
        "ai_decision_support": parsed.get("decision_support"),
        "ai_valuation_opinion": parsed.get("ai_valuation_opinion"),
        "ai_signal_agreement": parsed.get("ai_signal_agreement"),
        "ai_final_alert_action": parsed.get("ai_final_alert_action"),
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
        "ai_technical_view": None,
        "ai_fair_value_view": None,
        "ai_data_quality_view": None,
        "ai_opportunity": None,
        "ai_decision_support": None,
        "ai_valuation_opinion": "DATOS_INSUFICIENTES",
        "ai_signal_agreement": "NEUTRAL",
        "ai_final_alert_action": "NO_ENVIAR",
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
            "fair_value_estimate": row.get("fair_value_estimate"),
            "conservative_fair_value": row.get("conservative_fair_value"),
            "margin_of_safety_pct": row.get("margin_of_safety_pct"),
            "suggested_buy_price": row.get("suggested_buy_price"),
            "sell_score": row.get("sell_score"),
            "sell_signal": row.get("sell_signal"),
            "suggested_sell_price": row.get("suggested_sell_price"),
            "sell_thesis": row.get("ai_sell_thesis"),
            "ai_valuation_opinion": row.get("ai_valuation_opinion"),
            "ai_signal_agreement": row.get("ai_signal_agreement"),
            "ai_final_alert_action": row.get("ai_final_alert_action"),
            "peer_group": row.get("peer_group"),
            "peer_valuation_label": row.get("peer_valuation_label"),
            "peer_relative_score": row.get("peer_relative_score"),
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
                    "Usa lenguaje natural, breve y funcional. Los ratios deben aparecer como respaldo, con explicacion simple de que significan. "
                    "Debe separar oportunidades de compra, posiciones caras con posible venta y riesgos. "
                    "discord_summary debe ser muy conciso, maximo 900 caracteres, pensado para Discord. "
                    "full_report debe ser el analisis mas completo posible para web/BigQuery, con secciones claras: panorama general, compras, ventas, cambios, riesgos, datos faltantes, tecnica y seguimiento. "
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


def build_weekly_summary(config, weekly_rows):
    if not config.get("openai_api_key"):
        raise RuntimeError("OPENAI_API_KEY secret is required to generate weekly summary")
    client = OpenAI(api_key=config["openai_api_key"])
    response = client.responses.create(
        model=config["openai_model"],
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Crea un resumen semanal en espanol para Discord. "
                    "Usa lenguaje natural, breve y funcional. Si mencionas ratios o estados tecnicos, explica su significado practico. "
                    "Debe enfocarse en lo mas importante de la semana: cambios de estado, movimientos fuertes de precio, deterioro o mejora de riesgo, cambios de tendencia tecnica semanal/mensual y consideraciones para monitorear la proxima semana. "
                    "discord_summary debe ser muy conciso, maximo 900 caracteres, pensado para Discord. "
                    "full_report debe ser el reporte semanal mas completo posible para web/BigQuery, con secciones claras: resumen ejecutivo, cambios de estado, ventas, oportunidades, riesgos, tendencias, calidad de datos y seguimiento para la proxima semana. "
                    "No des recomendacion financiera personalizada. No repitas todas las acciones si no hay cambios relevantes. "
                    f"weekly_rows={json.dumps(weekly_rows, ensure_ascii=True, default=str)}"
                ),
            },
        ],
        text=_json_schema("weekly_portfolio_summary", WEEKLY_SUMMARY_SCHEMA),
    )
    return _extract_json(response)
