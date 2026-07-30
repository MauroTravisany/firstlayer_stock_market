import requests


DISCORD_GREEN = 0x2ECC71
DISCORD_RED = 0xE74C3C
DISCORD_GOLD = 0xF1C40F
DISCORD_BLUE = 0x3498DB
DISCORD_GRAY = 0x95A5A6


def _detect_webhook_type(config):
    configured = (config.get("alert_webhook_type") or "auto").lower()
    if configured != "auto":
        return configured
    url = config.get("alert_webhook_url") or ""
    if "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url:
        return "discord"
    return "slack"


def _money_clp(value):
    value = float(value or 0)
    return f"${value:,.0f} CLP".replace(",", ".")


def _number(value, decimals=2):
    if value is None:
        return "NA"
    return str(round(float(value), decimals))


def _signed_money_clp(value):
    value = float(value or 0)
    if value > 0:
        return f"+{_money_clp(value)}"
    if value < 0:
        return f"-{_money_clp(abs(value))}"
    return _money_clp(value)


def _plain_status_label(value):
    labels = {
        "SOBRE_OBJETIVO": "positivo sobre objetivo",
        "OBJETIVO_CUMPLIDO": "positivo dentro del objetivo",
        "POSITIVO_BAJO_OBJETIVO": "positivo bajo objetivo",
        "SIN_CIERRES": "sin cierres",
        "NEGATIVO": "negativo",
        "SEMANA_POSITIVA_SOBRE_OBJETIVO": "semana positiva sobre objetivo",
        "SEMANA_POSITIVA": "semana positiva",
        "SEMANA_SIN_RESULTADO": "semana sin resultado",
        "SEMANA_NEGATIVA": "semana negativa",
    }
    return labels.get(value or "", value or "sin estado")


def _trade_line(row):
    profile_adjustment = row.get("profile_adjustment_summary")
    adjustment_text = "" if not profile_adjustment or profile_adjustment == "NO_PROFILE_ADJUSTMENT" else " | ajuste perfil activo"
    return (
        f"{row.get('strategy_version')} {row.get('signal_hour')} {row.get('ticker')} {row.get('paper_signal')} {row.get('setup_type')} | "
        f"{row.get('cycle_profile') or row.get('trading_style')} | "
        f"entrada {_number(row.get('theoretical_entry_price'), 2)} | "
        f"stop {_number(row.get('stop_loss'), 2)} | "
        f"tp1 {_number(row.get('take_profit_1'), 2)} | "
        f"macro {_number(row.get('macro_alignment_score'), 2)} {row.get('macro_regime')} | "
        f"factor {_number(row.get('factor_alignment_score'), 2)} | "
        f"miedo {_number(row.get('market_fear_score'), 0)} {row.get('market_fear_regime')} | "
        f"resultados {row.get('earnings_event_status')} | "
        f"monto {_money_clp(row.get('position_notional_clp'))}{adjustment_text}"
    )


def _closed_line(row):
    return (
        f"{row.get('strategy_version')} {row.get('signal_hour')} {row.get('ticker')} {row.get('result_label')} | "
        f"entrada {_number(row.get('theoretical_entry_price'), 2)} | "
        f"salida {_number(row.get('exit_price'), 2)} | "
        f"macro {_number(row.get('macro_alignment_score'), 2)} | "
        f"miedo {_number(row.get('market_fear_score'), 0)} | "
        f"resultados {row.get('earnings_event_status')} | "
        f"PnL {_money_clp(row.get('net_pnl_clp'))}"
    )


def build_discord_payload(summary, new_trades, closed_trades, feedback=None):
    pnl = float(summary.get("realized_pnl_clp") or 0)
    status = summary.get("daily_result_status") or "SIN_CIERRES"
    color = DISCORD_BLUE
    if pnl >= float(summary.get("daily_target_min_clp") or 25000):
        color = DISCORD_GREEN
    elif pnl < 0:
        color = DISCORD_RED
    elif status == "SIN_CIERRES":
        color = DISCORD_GRAY
    else:
        color = DISCORD_GOLD

    new_lines = "\n".join([_trade_line(row) for row in new_trades]) or "Sin entradas nuevas."
    closed_lines = "\n".join([_closed_line(row) for row in closed_trades]) or "Sin cierres realizados."
    day_start = summary.get("day_start_equity_clp")
    day_end = summary.get("day_end_equity_clp")
    week_pnl = summary.get("week_to_date_pnl_clp")
    week_status = summary.get("week_to_date_status")
    day_read = summary.get("daily_plain_read") or "Resumen diario disponible."
    week_read = summary.get("weekly_plain_read") or "Resumen semanal disponible."

    return {
        "embeds": [
            {
                "title": f"Paper trading diario | {summary.get('summary_date')}",
                "description": (
                    f"{day_read}\n"
                    f"{week_read}\n"
                    "Lectura: se mide dinero ficticio; sirve para evaluar consistencia, no para operar dinero real."
                ),
                "color": color,
                "fields": [
                    {
                        "name": "Capital simulado",
                        "value": (
                            f"Inicio del dia: {_money_clp(day_start)}\n"
                            f"Cierre del dia: {_money_clp(day_end)}\n"
                            f"Resultado del dia: {_signed_money_clp(pnl)} ({_plain_status_label(status)})"
                        ),
                        "inline": False,
                    },
                    {
                        "name": "Actividad del dia",
                        "value": (
                            f"Entradas nuevas: {summary.get('new_trade_count', 0)}\n"
                            f"En observacion: {summary.get('watch_count', 0)}\n"
                            f"Cierres: {summary.get('closed_trade_count', 0)}\n"
                            f"Ganados: {summary.get('winning_trade_count', 0)} | Perdidos: {summary.get('losing_trade_count', 0)}"
                        ),
                        "inline": False,
                    },
                    {
                        "name": "Semana en curso",
                        "value": (
                            f"Periodo: {summary.get('week_start')} a {summary.get('week_end')}\n"
                            f"Resultado semanal acumulado: {_signed_money_clp(week_pnl)} ({_plain_status_label(week_status)})\n"
                            f"Cierres semana: {summary.get('week_to_date_closed_trades', 0)}\n"
                            f"Ganados: {summary.get('week_to_date_winning_trades', 0)} | "
                            f"Perdidos: {summary.get('week_to_date_losing_trades', 0)} | "
                            f"Win rate: {_number(summary.get('week_to_date_win_rate_pct'), 1)}%"
                        ),
                        "inline": False,
                    },
                    {
                        "name": "Meta diaria",
                        "value": (
                            f"Rango objetivo ficticio: {_money_clp(summary.get('daily_target_min_clp'))} a "
                            f"{_money_clp(summary.get('daily_target_max_clp'))}.\n"
                            "Prioridad actual: evitar perdidas grandes y buscar avances moderados."
                        ),
                        "inline": False,
                    },
                    {
                        "name": "Historico acumulado",
                        "value": (
                            f"Cerrados: {summary.get('all_closed_trades', 0)} | "
                            f"Win rate: {_number(summary.get('all_win_rate_pct'), 2)}% | "
                            f"Resultado total: {_signed_money_clp(summary.get('all_realized_pnl_clp'))}"
                        ),
                        "inline": False,
                    },
                    {
                        "name": "Comparativa v1-v4",
                        "value": str(summary.get("strategy_performance_summary") or "Sin historico por estrategia")[:1024],
                        "inline": False,
                    },
                    {"name": "Entradas/Vigilancia", "value": new_lines[:1024], "inline": False},
                    {"name": "Cierres", "value": closed_lines[:1024], "inline": False},
                    {
                        "name": "Feedback IA",
                        "value": str((feedback or {}).get("executive_summary") or "Feedback IA no generado.")[:1024],
                        "inline": False,
                    },
                ],
                "footer": {"text": "Paper trading: simulacion, no ejecuta dinero real. Incluye spread y slippage estimados."},
            }
        ]
    }


def _strategy_line(row):
    return (
        f"{row.get('strategy_version')} {row.get('strategy_name')} | "
        f"PnL {_money_clp(row.get('realized_pnl_clp'))} | "
        f"win {_number(row.get('win_rate_pct'), 1)}% | "
        f"cerrados {row.get('closed_count', 0)} | "
        f"SL {row.get('stop_loss_count', 0)} TP {row.get('take_profit_count', 0)}"
    )


def _ticker_line(row):
    return (
        f"{row.get('ticker')} | PnL {_money_clp(row.get('realized_pnl_clp'))} | "
        f"win {_number(row.get('win_rate_pct'), 1)}% | cerrados {row.get('closed_count', 0)}"
    )


def _daily_line(row):
    return (
        f"{row.get('summary_date')}: {_money_clp(row.get('realized_pnl_clp'))} | "
        f"{row.get('daily_result_status')} | nuevos {row.get('new_trade_count', 0)} | "
        f"cerrados {row.get('closed_trade_count', 0)}"
    )


def build_weekly_discord_payload(weekly_summary, strategy_performance, ticker_performance):
    pnl = float(weekly_summary.get("realized_pnl_clp") or 0)
    status = weekly_summary.get("weekly_result_status") or "SIN_CIERRES"
    color = DISCORD_BLUE
    if status == "SOBRE_OBJETIVO_SEMANAL":
        color = DISCORD_GREEN
    elif pnl < 0:
        color = DISCORD_RED
    elif status == "SIN_CIERRES":
        color = DISCORD_GRAY
    else:
        color = DISCORD_GOLD

    daily_breakdown = weekly_summary.get("daily_breakdown") or []
    daily_lines = "\n".join(_daily_line(row) for row in daily_breakdown) or "Sin dias calculados."
    strategy_lines = "\n".join(_strategy_line(row) for row in strategy_performance) or "Sin cierres por estrategia."
    ticker_lines = "\n".join(_ticker_line(row) for row in ticker_performance) or "Sin cierres por activo."

    return {
        "embeds": [
            {
                "title": f"Paper trading semanal | {weekly_summary.get('week_start')} a {weekly_summary.get('week_end')}",
                "description": (
                    "Consolidado global de la semana en paper trading. "
                    "Mide resultado ficticio, consistencia, estrategias y activos que mas movieron el resultado."
                ),
                "color": color,
                "fields": [
                    {
                        "name": "Resultado semanal",
                        "value": (
                            f"{status} | PnL {_money_clp(pnl)} | "
                            f"objetivo semanal {_money_clp(weekly_summary.get('weekly_target_min_clp'))} a "
                            f"{_money_clp(weekly_summary.get('weekly_target_max_clp'))}"
                        ),
                        "inline": False,
                    },
                    {
                        "name": "Actividad",
                        "value": (
                            f"Dias con resumen: {weekly_summary.get('days_with_summary', 0)} | "
                            f"nuevos: {weekly_summary.get('new_trade_count', 0)} | "
                            f"vigilancia: {weekly_summary.get('watch_count', 0)} | "
                            f"abiertos fin semana: {weekly_summary.get('open_trade_count', 0)}"
                        ),
                        "inline": False,
                    },
                    {
                        "name": "Cierres",
                        "value": (
                            f"Cerrados: {weekly_summary.get('closed_trade_count', 0)} | "
                            f"ganaron: {weekly_summary.get('winning_trade_count', 0)} | "
                            f"perdieron: {weekly_summary.get('losing_trade_count', 0)} | "
                            f"win rate: {_number(weekly_summary.get('win_rate_pct'), 1)}% | "
                            f"SL: {weekly_summary.get('stop_loss_count', 0)} | TP: {weekly_summary.get('take_profit_count', 0)}"
                        ),
                        "inline": False,
                    },
                    {"name": "Por dia", "value": daily_lines[:1024], "inline": False},
                    {"name": "Estrategias v1-v4", "value": strategy_lines[:1024], "inline": False},
                    {"name": "Activos que mas impactaron", "value": ticker_lines[:1024], "inline": False},
                ],
                "footer": {"text": "Paper trading semanal: simulacion, no ejecuta dinero real."},
            }
        ]
    }


def send_weekly_alert(config, weekly_summary, strategy_performance, ticker_performance):
    url = config.get("alert_webhook_url")
    if not url:
        return False, "NO_WEBHOOK_URL"

    webhook_type = _detect_webhook_type(config)
    if webhook_type == "discord":
        payload = build_weekly_discord_payload(weekly_summary, strategy_performance, ticker_performance)
        response = requests.post(url, json=payload, timeout=30)
    else:
        text = (
            f"Paper trading semanal {weekly_summary.get('week_start')} a {weekly_summary.get('week_end')}: "
            f"{weekly_summary.get('weekly_result_status')} | PnL {_money_clp(weekly_summary.get('realized_pnl_clp'))}"
        )
        response = requests.post(url, json={"text": text}, timeout=30)

    if response.status_code >= 300:
        return False, f"{response.status_code}: {response.text}"
    return True, None


def send_alert(config, summary, new_trades, closed_trades, feedback=None):
    url = config.get("alert_webhook_url")
    if not url:
        return False, "NO_WEBHOOK_URL"

    webhook_type = _detect_webhook_type(config)
    if webhook_type == "discord":
        response = requests.post(url, json=build_discord_payload(summary, new_trades, closed_trades, feedback), timeout=30)
    else:
        response = requests.post(url, json={"text": summary.get("discord_summary") or "Paper trading diario"}, timeout=30)

    if response.status_code >= 300:
        return False, f"{response.status_code}: {response.text}"
    return True, None
