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
- Si un activo es semiconductor, cripto, software, publicidad digital o consumo global, revisa si el macro_alignment_score deberia pesar mas o menos.
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
