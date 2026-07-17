import requests


DISCORD_CONTENT_LIMIT = 2000
SLACK_TEXT_LIMIT = 12000
DEFAULT_MIN_FINAL_SCORE = 6.0
DEFAULT_MIN_CONFIDENCE = 0.65


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


def build_alert_text(summary, opportunity_rows=None):
    if opportunity_rows is not None:
        lines = [f"*{summary['alert_title']}*", ""]
        lines.append("Oportunidades claras detectadas:")
        for row in opportunity_rows:
            lines.append(
                "- {ticker}: score={score}, confianza={confidence}. {summary}".format(
                    ticker=row.get("ticker"),
                    score=round(float(row.get("final_score") or 0), 2),
                    confidence=round(float(row.get("confidence_score") or 0), 2),
                    summary=row.get("ai_summary") or row.get("ai_opportunity") or "Ver detalle en Looker Studio.",
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


def send_webhook_alert(config, summary, analysis_rows=None):
    url = config.get("alert_webhook_url")
    if not url:
        return False, "ALERT_WEBHOOK_URL not configured"

    opportunity_rows = clear_opportunity_rows(analysis_rows or [])
    if not opportunity_rows:
        return False, "NO_CLEAR_OPPORTUNITIES"

    text = build_alert_text(summary, opportunity_rows)
    webhook_type = _detect_webhook_type(config)
    if webhook_type == "discord":
        payload = {"content": _truncate_text(text, DISCORD_CONTENT_LIMIT)}
    else:
        payload = {"text": _truncate_text(text, SLACK_TEXT_LIMIT)}

    response = requests.post(url, json=payload, timeout=30)
    if response.status_code >= 300:
        return False, f"Webhook error {response.status_code}: {response.text}"
    return True, None
