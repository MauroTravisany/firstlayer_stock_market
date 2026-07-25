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


def _trade_line(row):
    return (
        f"{row.get('ticker')} {row.get('paper_signal')} {row.get('setup_type')} | "
        f"entrada {_number(row.get('theoretical_entry_price'), 2)} | "
        f"stop {_number(row.get('stop_loss'), 2)} | "
        f"tp1 {_number(row.get('take_profit_1'), 2)} | "
        f"monto {_money_clp(row.get('position_notional_clp'))}"
    )


def _closed_line(row):
    return (
        f"{row.get('ticker')} {row.get('result_label')} | "
        f"entrada {_number(row.get('theoretical_entry_price'), 2)} | "
        f"salida {_number(row.get('exit_price'), 2)} | "
        f"PnL {_money_clp(row.get('net_pnl_clp'))}"
    )


def build_discord_payload(summary, new_trades, closed_trades):
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

    return {
        "embeds": [
            {
                "title": f"Paper trading diario | {summary.get('summary_date')}",
                "description": summary.get("discord_summary") or "Resumen paper trading.",
                "color": color,
                "fields": [
                    {"name": "Resultado del dia", "value": f"{status} | PnL {_money_clp(pnl)}", "inline": False},
                    {
                        "name": "Trades",
                        "value": (
                            f"Nuevos: {summary.get('new_trade_count', 0)} | "
                            f"Cerrados: {summary.get('closed_trade_count', 0)} | "
                            f"Ganaron: {summary.get('winning_trade_count', 0)} | "
                            f"Perdieron: {summary.get('losing_trade_count', 0)}"
                        ),
                        "inline": False,
                    },
                    {
                        "name": "Objetivo ficticio",
                        "value": f"{_money_clp(summary.get('daily_target_min_clp'))} a {_money_clp(summary.get('daily_target_max_clp'))} diarios",
                        "inline": False,
                    },
                    {
                        "name": "Historico",
                        "value": (
                            f"Cerrados: {summary.get('all_closed_trades', 0)} | "
                            f"Win rate: {_number(summary.get('all_win_rate_pct'), 2)}% | "
                            f"PnL total {_money_clp(summary.get('all_realized_pnl_clp'))}"
                        ),
                        "inline": False,
                    },
                    {"name": "Entradas/Vigilancia", "value": new_lines[:1024], "inline": False},
                    {"name": "Cierres", "value": closed_lines[:1024], "inline": False},
                ],
                "footer": {"text": "Paper trading: simulacion, no ejecuta dinero real. Incluye spread y slippage estimados."},
            }
        ]
    }


def send_alert(config, summary, new_trades, closed_trades):
    url = config.get("alert_webhook_url")
    if not url:
        return False, "NO_WEBHOOK_URL"

    webhook_type = _detect_webhook_type(config)
    if webhook_type == "discord":
        response = requests.post(url, json=build_discord_payload(summary, new_trades, closed_trades), timeout=30)
    else:
        response = requests.post(url, json={"text": summary.get("discord_summary") or "Paper trading diario"}, timeout=30)

    if response.status_code >= 300:
        return False, f"{response.status_code}: {response.text}"
    return True, None
