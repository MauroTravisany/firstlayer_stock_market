import json

from openai import OpenAI


def _json_default(value):
    return str(value)


def _compact_rows(rows, max_rows=12):
    return rows[:max_rows]


def generate_trading_feedback(config, summary, new_trades, closed_trades, strategy_performance, asset_profiles=None):
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
        "asset_profiles": _compact_rows(asset_profiles or [], max_rows=30),
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
- Evalua miedo del mercado: market_fear_score y market_fear_regime. Si hay miedo alto, exige mejor calidad de setup o menor tamano; si hay euforia, revisa riesgo de comprar tarde.
- Evalua resultados corporativos: earnings_event_status, days_to_earnings, surprise_pct si existe y earnings_context_note. Cerca de resultados reduce confianza por gap risk.
- Si hubo resultado reciente, no basta EPS positivo: pide revisar calidad del resultado, guidance, flujo de caja libre, margenes y capex. Ejemplo importante: una empresa puede reportar ingresos/EPS fuertes y caer si el FCF se deteriora por inversiones en IA.
- Si un activo es semiconductor, cripto, software, publicidad digital, consumo global o mega cap defensiva/growth, revisa si el factor_alignment_score y el macro_alignment_score deberian pesar mas o menos.
- Usa asset_profiles como fuente de verdad de sensibilidades actuales. Ahi estan los pesos macro, pesos tecnicos y sensibilidades finas usadas para calcular el trade.
- Si propones modificar sensibilidad, indica ticker, campo exacto, valor actual, valor sugerido, razon y evidencia. No sugieras cambios sin relacionarlos con resultados observados.
- Para cripto, diferencia BTC dominante, rotacion altcoin, volumen relativo, liquidez y risk-off. Si faltan flujos reales on-chain/exchange/funding, dilo como brecha de datos.
- Si faltan noticias externas o detalle real de earnings, indicalo como informacion a revisar, no lo inventes.
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


def generate_weekly_strategy_review(
    config,
    week_start,
    week_end,
    daily_feedback,
    multiweek_results,
    asset_profiles=None,
    cycle_profile_performance=None,
):
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
        "asset_profiles": _compact_rows(asset_profiles or [], max_rows=40),
        "cycle_profile_performance": _compact_rows(cycle_profile_performance or [], max_rows=40),
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
- Evalua market_fear_regime y earnings_event_status: detecta si el sistema abre demasiados trades con miedo alto, euforia, resultados inminentes o resultados recientes de baja calidad.
- Cuando existan resultados recientes, diferencia sorpresa EPS de calidad del resultado. Pide informacion adicional si falta FCF, capex, guidance o reaccion post-earnings.
- Usa asset_profiles para revisar los valores actuales de sensibilidad usados por ticker. Puedes recomendar cambios a:
  trend_weight, momentum_weight, volume_weight, volatility_weight, regime_weight,
  growth_sensitivity, defensive_sensitivity, energy_sensitivity, crypto_sensitivity,
  usd_sensitivity, rates_sensitivity, geopolitical_sensitivity, risk_appetite_sensitivity,
  semiconductor_cycle_sensitivity, ai_capex_sensitivity, consumer_cycle_sensitivity,
  advertising_cycle_sensitivity, energy_input_sensitivity, electricity_cost_sensitivity,
  rates_duration_sensitivity, usd_revenue_sensitivity, geopolitical_supply_sensitivity,
  liquidity_risk_sensitivity, crypto_flow_sensitivity, btc_dominance_sensitivity,
  regulatory_sensitivity, breakout_preference, pullback_preference,
  support_rebound_preference, volume_confirmation_importance.
- Usa cycle_profile_performance para detectar si el problema es de estrategia v1-v4, de ticker especifico o del perfil/factor.
- Para BTC/ETH/COIN, revisa si el proxy de flujo cripto fue suficiente o si falta informacion externa como funding, open interest, stablecoin flows o exchange netflows.
- El sistema debe aprender de forma controlada: guardar hipotesis, comparar resultados y pedir aprobacion antes de tocar reglas productivas.
- approval_status general debe ser uno de: PENDIENTE_APROBACION, APLICAR_EN_BACKTEST, PENDIENTE_OBSERVACION, SIN_CAMBIOS, SIN_IA.
- Solo marca APLICAR_EN_BACKTEST una recomendacion de sensibilidad si se repite en feedback diario o tiene evidencia multiweek/cycle_profile suficiente.

Devuelve SOLO JSON valido con estas claves:
repeated_patterns: string,
recommendations: array de objetos con claves recommendation_type, affected_ticker, affected_strategy, affected_profile_field, current_value, suggested_value, suggested_change, evidence, times_repeated, expected_impact, risk_level, confidence_score, approval_status,
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
