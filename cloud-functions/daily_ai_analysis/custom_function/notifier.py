import requests


DISCORD_CONTENT_LIMIT = 2000
DISCORD_FIELD_LIMIT = 1024
SLACK_TEXT_LIMIT = 12000
DEFAULT_MIN_FINAL_SCORE = 6.0
DEFAULT_MIN_CONFIDENCE = 0.65
DEFAULT_MIN_SELL_SCORE = 7.0
DISCORD_GREEN = 0x2ECC71
DISCORD_RED = 0xE74C3C
DISCORD_GOLD = 0xF1C40F


def _detect_webhook_type(config):
    webhook_type = config.get("alert_webhook_type") or "auto"
    url = config.get("alert_webhook_url") or ""
    if webhook_type != "auto":
        return webhook_type
    if "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url:
        return "discord"
    return "slack"


def clear_opportunity_rows(analysis_rows, min_final_score=DEFAULT_MIN_FINAL_SCORE, min_confidence=DEFAULT_MIN_CONFIDENCE):
    rows = []
    for row in analysis_rows:
        if row.get("signal") != "COMPRAR_OBSERVAR":
            continue
        final_score = row.get("final_score")
        confidence_score = row.get("confidence_score")
        if final_score is None or float(final_score) < min_final_score:
            continue
        if confidence_score is None or float(confidence_score) < min_confidence:
            continue
        rows.append(row)
    return sorted(rows, key=lambda item: item.get("final_score") or 0, reverse=True)


def clear_sell_rows(analysis_rows, min_sell_score=DEFAULT_MIN_SELL_SCORE, min_confidence=DEFAULT_MIN_CONFIDENCE):
    rows = []
    for row in analysis_rows:
        if row.get("sell_signal") != "VENTA_CLARA" and row.get("signal") != "VENDER_OBSERVAR":
            continue
        sell_score = row.get("sell_score")
        confidence_score = row.get("confidence_score")
        if sell_score is None or float(sell_score) < min_sell_score:
            continue
        if confidence_score is None or float(confidence_score) < min_confidence:
            continue
        rows.append(row)
    return sorted(rows, key=lambda item: item.get("sell_score") or 0, reverse=True)


def _normalized_confidence(value):
    if value is None:
        return 0.0
    confidence = float(value)
    if confidence > 1:
        return confidence / 100
    return confidence


def build_alert_text(summary, opportunity_rows=None, sell_rows=None):
    if opportunity_rows is not None or sell_rows is not None:
        lines = [f"*{summary['alert_title']}*", ""]
        if opportunity_rows:
            lines.append("Oportunidades claras de compra detectadas:")
            for row in opportunity_rows:
                confidence = _normalized_confidence(row.get("confidence_score"))
                lines.append(
                    "- {ticker}: score={score}, confianza={confidence}. {summary}".format(
                        ticker=row.get("ticker"),
                        score=round(float(row.get("final_score") or 0), 2),
                        confidence=round(confidence, 2),
                        summary=row.get("ai_summary") or row.get("ai_opportunity") or "Ver detalle en Looker Studio.",
                    )
                )
        if sell_rows:
            if opportunity_rows:
                lines.append("")
            lines.append("Alertas claras de venta/sobrevaloracion:")
            for row in sell_rows:
                confidence = _normalized_confidence(row.get("confidence_score"))
                lines.append(
                    "- {ticker}: score_venta={score}, precio_actual={price}, zona_revision={sell_price}, confianza={confidence}. {summary}".format(
                        ticker=row.get("ticker"),
                        score=round(float(row.get("sell_score") or 0), 2),
                        price=round(float(row.get("last_close") or 0), 2),
                        sell_price=round(float(row.get("suggested_sell_price") or 0), 2),
                        confidence=round(confidence, 2),
                        summary=row.get("ai_sell_thesis") or row.get("ai_sell_reasons") or "Ver detalle en Looker Studio.",
                    )
                )
        lines.append("")
        lines.append("Detalle completo en Looker Studio / BigQuery.")
        return "\n".join(lines)

    return (
        f"*{summary['alert_title']}*\n\n"
        f"{summary['portfolio_summary']}\n\n"
        f"*Oportunidades*\n{summary['top_opportunities']}\n\n"
        f"*Sobrevaloradas*\n{summary['overvalued_summary']}\n\n"
        f"*Riesgos*\n{summary['risk_summary']}"
    )


def _truncate_text(text, limit):
    if len(text) <= limit:
        return text
    suffix = "\n\n[Mensaje truncado. Ver detalle completo en Looker Studio / BigQuery.]"
    return text[: max(0, limit - len(suffix))].rstrip() + suffix


def _short_text(text, limit):
    if not text:
        return "Ver detalle en Looker Studio."
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _buy_fields(opportunity_rows):
    fields = []
    for row in opportunity_rows[:10]:
        ticker = row.get("ticker")
        score = round(float(row.get("final_score") or 0), 2)
        confidence = round(_normalized_confidence(row.get("confidence_score")), 2)
        text = row.get("ai_summary") or row.get("ai_opportunity") or "Ver detalle en Looker Studio."
        fields.append(
            {
                "name": f"{ticker} | score {score} | confianza {confidence}",
                "value": _short_text(text, DISCORD_FIELD_LIMIT),
                "inline": False,
            }
        )
    return fields


def _sell_fields(sell_rows):
    fields = []
    for row in sell_rows[:10]:
        ticker = row.get("ticker")
        score = round(float(row.get("sell_score") or 0), 2)
        confidence = round(_normalized_confidence(row.get("confidence_score")), 2)
        price = round(float(row.get("last_close") or 0), 2)
        sell_price = round(float(row.get("suggested_sell_price") or 0), 2)
        text = row.get("ai_sell_thesis") or row.get("ai_sell_reasons") or "Ver detalle en Looker Studio."
        fields.append(
            {
                "name": f"{ticker} | venta {score} | actual {price} | revisar {sell_price} | confianza {confidence}",
                "value": _short_text(text, DISCORD_FIELD_LIMIT),
                "inline": False,
            }
        )
    return fields


def build_discord_payload(summary, opportunity_rows, sell_rows=None):
    sell_rows = sell_rows or []
    embeds = []
    if opportunity_rows:
        embeds.append(
            {
                "title": "Oportunidades claras de compra",
                "description": "Acciones con senal `COMPRAR_OBSERVAR`, score alto y confianza suficiente.",
                "color": DISCORD_GREEN,
                "fields": _buy_fields(opportunity_rows),
                "footer": {"text": "Detalle completo en Looker Studio / BigQuery"},
            }
        )
    if sell_rows:
        embeds.append(
            {
                "title": "Alertas claras de venta",
                "description": "Acciones con `VENTA_CLARA` o `VENDER_OBSERVAR`, multiples exigentes y confianza suficiente.",
                "color": DISCORD_RED,
                "fields": _sell_fields(sell_rows),
                "footer": {"text": "No es recomendacion personalizada. Revisar detalle en Looker Studio / BigQuery"},
            }
        )
    if not embeds:
        embeds.append(
            {
                "title": summary.get("alert_title") or "Cartera sin alertas claras",
                "description": "No se detectaron compras ni ventas claras con los umbrales actuales.",
                "color": DISCORD_GOLD,
            }
        )
    return {"embeds": embeds}


def send_webhook_alert(config, summary, analysis_rows=None):
    url = config.get("alert_webhook_url")
    if not url:
        return False, "ALERT_WEBHOOK_URL not configured"

    opportunity_rows = clear_opportunity_rows(analysis_rows or [])
    sell_rows = clear_sell_rows(analysis_rows or [])
    if not opportunity_rows and not sell_rows:
        return False, "NO_CLEAR_OPPORTUNITIES"

    text = build_alert_text(summary, opportunity_rows, sell_rows)
    webhook_type = _detect_webhook_type(config)
    if webhook_type == "discord":
        payload = build_discord_payload(summary, opportunity_rows, sell_rows)
    else:
        payload = {"text": _truncate_text(text, SLACK_TEXT_LIMIT)}

    response = requests.post(url, json=payload, timeout=30)
    if response.status_code >= 300:
        return False, f"Webhook error {response.status_code}: {response.text}"
    return True, None
