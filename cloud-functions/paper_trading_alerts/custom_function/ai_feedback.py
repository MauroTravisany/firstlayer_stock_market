import json

from openai import OpenAI


def _json_default(value):
    return str(value)


def _compact_rows(rows, max_rows=12):
    return rows[:max_rows]


def generate_trading_feedback(config, summary, new_trades, closed_trades, strategy_performance):
    if not config.get("openai_api_key"):
        return {
            "executive_summary": "Feedback IA omitido: no existe OPENAI_API_KEY configurada.",
            "what_worked": "",
            "what_failed": "",
            "risk_notes": "",
            "parameter_suggestions": "",
            "news_needed": "",
            "next_actions": "Configurar OPENAI_API_KEY si se quiere retroalimentacion automatica.",
            "confidence_score": 0,
            "raw_response": "{}",
        }

    payload = {
        "summary": {key: _json_default(value) for key, value in summary.items()},
        "new_trades": _compact_rows(new_trades),
        "closed_trades": _compact_rows(closed_trades),
        "strategy_performance": _compact_rows(strategy_performance),
    }
    prompt = f"""
Eres un revisor profesional de un sistema de paper trading. El sistema NO opera dinero real.

Objetivo del usuario:
- Buscar consistencia.
- Ideal observado: 25.000 a 100.000 CLP diarios ficticios, sin forzar entradas.
- Preferencia actual: trades mas largos, versiones v1-v4 comparables, acciones grandes y BTC/ETH.

Reglas:
- Responde siempre en espanol.
- No prometas rentabilidad.
- No recomiendes operar dinero real.
- Separa observaciones basadas en datos de hipotesis.
- Evalua costos, spread/slippage, sobreoperacion, stops, horizontes y diferencias por estrategia.
- Evalua si el contexto macro usado por activo tiene sentido: growth, defensivo, energia/commodities, cripto, dolar, tasas, euro, geopolitica y apetito por riesgo.
- Evalua tambien el perfil fino por activo: sector_profile, cycle_profile, factor_alignment_score y factor_risk_notes.
- Si un activo es semiconductor, cripto, software, publicidad digital, consumo global o mega cap defensiva/growth, revisa si el factor_alignment_score y el macro_alignment_score deberian pesar mas o menos.
- Para cripto, diferencia BTC dominante, rotacion altcoin, volumen relativo, liquidez y risk-off. Si faltan flujos reales on-chain/exchange/funding, dilo como brecha de datos.
- Si faltan noticias externas, indicalo como informacion a revisar, no lo inventes.
- Sugiere cambios de parametros solo como hipotesis para revisar, nunca como cambio automatico.

Devuelve SOLO JSON valido con estas claves:
executive_summary, what_worked, what_failed, risk_notes, parameter_suggestions, news_needed, next_actions, confidence_score.
confidence_score debe ser un numero entre 0 y 1.

Datos:
{json.dumps(payload, ensure_ascii=True, default=_json_default)}
""".strip()

    client = OpenAI(api_key=config["openai_api_key"], timeout=60)
    response = client.responses.create(
        model=config["openai_model"],
        input=prompt,
    )
    raw_text = response.output_text.strip()
    try:
        feedback = json.loads(raw_text)
    except json.JSONDecodeError:
        feedback = {
            "executive_summary": raw_text[:3000],
            "what_worked": "",
            "what_failed": "",
            "risk_notes": "",
            "parameter_suggestions": "",
            "news_needed": "",
            "next_actions": "",
            "confidence_score": 0.3,
        }
    feedback["raw_response"] = raw_text
    return feedback


def generate_weekly_strategy_review(config, week_start, week_end, daily_feedback, multiweek_results):
    if not config.get("openai_api_key"):
        return {
            "repeated_patterns": "Revision semanal omitida: no existe OPENAI_API_KEY configurada.",
            "recommendations": [],
            "evidence_summary": "",
            "multiweek_results_summary": "",
            "application_policy": "No aplicar cambios sin API key.",
            "approval_status": "SIN_IA",
            "confidence_score": 0,
            "raw_response": "{}",
        }

    payload = {
        "week_start": str(week_start),
        "week_end": str(week_end),
        "daily_feedback": daily_feedback,
        "multiweek_results": multiweek_results,
    }
    prompt = f"""
Eres un comite semanal de revision de un sistema de paper trading. El sistema NO opera dinero real.

Objetivo:
- Revisar todas las sugerencias diarias de IA de la semana.
- Detectar patrones repetidos y separar ruido de evidencia.
- Contrastar sugerencias con resultados de las ultimas semanas.
- Proponer cambios candidatos, pero NO aplicarlos automaticamente.

Reglas:
- Responde siempre en espanol.
- No prometas rentabilidad.
- No propongas aplicar una regla si aparece solo una vez y no hay evidencia en resultados.
- Una recomendacion debe quedar como APLICAR_EN_BACKTEST solo si se repite durante la semana y tiene soporte en resultados acumulados.
- Si falta historial suficiente, usa PENDIENTE_OBSERVACION.
- Incluye resultados acumulados de varias semanas cuando existan: win rate, P&L ficticio, estrategias/tickers que mejor o peor funcionaron.
- Evalua por activo, estrategia, macro_regime, stop, take profit, horarios y sobreoperacion.
- Evalua por cycle_profile y factor_alignment_score: identifica si ciertos perfiles de activo funcionan mejor/peor y si algun factor esta sobreponderado o subponderado.
- Para BTC/ETH/COIN, revisa si el proxy de flujo cripto fue suficiente o si falta informacion externa como funding, open interest, stablecoin flows o exchange netflows.
- El sistema debe aprender de forma controlada: guardar hipotesis, comparar resultados y pedir aprobacion antes de tocar reglas productivas.
- approval_status general debe ser uno de: PENDIENTE_APROBACION, APLICAR_EN_BACKTEST, PENDIENTE_OBSERVACION, SIN_CAMBIOS, SIN_IA.

Devuelve SOLO JSON valido con estas claves:
repeated_patterns: string,
recommendations: array de objetos con claves recommendation_type, affected_ticker, affected_strategy, suggested_change, evidence, times_repeated, expected_impact, risk_level, confidence_score, approval_status,
evidence_summary: string,
multiweek_results_summary: string,
application_policy: string,
approval_status: string,
confidence_score: number entre 0 y 1.

Datos:
{json.dumps(payload, ensure_ascii=True, default=_json_default)}
""".strip()

    client = OpenAI(api_key=config["openai_api_key"], timeout=90)
    response = client.responses.create(
        model=config["openai_model"],
        input=prompt,
    )
    raw_text = response.output_text.strip()
    try:
        review = json.loads(raw_text)
    except json.JSONDecodeError:
        review = {
            "repeated_patterns": raw_text[:3000],
            "recommendations": [],
            "evidence_summary": "",
            "multiweek_results_summary": "",
            "application_policy": "Respuesta IA no parseable; guardar solo como observacion.",
            "approval_status": "PENDIENTE_OBSERVACION",
            "confidence_score": 0.3,
        }
    review["raw_response"] = raw_text
    return review
