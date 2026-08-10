"""Create small deterministic CSV inputs for the Evidence dashboard CI build."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


FIXTURES = {
    "portfolio_latest.csv": [
        {
            "analysis_date": "2026-01-02",
            "ticker": "AAPL",
            "asset_type": "STOCK",
            "signal": "COMPRAR_OBSERVAR",
            "sell_signal": "MANTENER",
            "classification": "PRECIO_JUSTO",
            "valuation_model": "TECH_MEGACAP",
            "primary_metric": "forward_pe",
            "buy_multiple_guardrail_pass": "true",
            "final_score": "72.5",
            "sell_score": "20.0",
            "valuation_score": "70.0",
            "quality_score": "80.0",
            "momentum_score": "65.0",
            "technical_score": "68.0",
            "risk_score": "25.0",
            "margin_of_safety_pct": "0.12",
            "last_close": "200.0",
            "suggested_buy_price": "185.0",
            "suggested_sell_price": "240.0",
            "pe_ratio": "30.0",
            "forward_pe": "27.0",
            "price_to_sales": "8.0",
            "price_to_book": "12.0",
            "ev_to_ebitda": "22.0",
            "adaptive_forward_pe_limit": "29.0",
            "adaptive_price_to_sales_limit": "9.0",
            "adaptive_ev_to_ebitda_limit": "24.0",
            "peer_valuation_label": "EN_LINEA",
            "risk_level": "MEDIO",
            "technical_trend": "ALCISTA",
            "missing_data_impact": "BAJO",
            "confidence_score": "0.75",
            "ai_summary": "Resumen fixture",
            "ai_opportunity": "Oportunidad fixture",
            "ai_analysis": "Analisis fixture",
            "ai_fair_value_view": "Valor justo fixture",
            "ai_technical_view": "Tecnica fixture",
            "ai_risks": "Riesgos fixture",
            "ai_sell_thesis": "Venta fixture",
            "ai_sell_reasons": "Razones fixture",
            "ai_sell_price_view": "Precio venta fixture",
            "ai_decision_support": "Decision fixture",
            "ai_sell_decision_support": "Decision venta fixture",
            "data_discrepancies": "Sin discrepancias",
            "external_context_summary": "Contexto fixture",
        }
    ],
    "portfolio_history.csv": [
        {
            "analysis_date": "2026-08-08",
            "ticker": "AAPL",
            "previous_signal": "MANTENER",
            "signal": "COMPRAR_OBSERVAR",
            "final_score": "72.5",
            "final_score_change": "5.0",
            "last_close": "200.0",
            "signal_changed": "true",
        }
    ],
    "company_status_latest.csv": [
        {
            "ticker": "AAPL",
            "company_status": "OBSERVAR_COMPRA",
            "status_group": "COMPRA",
            "signal": "COMPRAR_OBSERVAR",
            "sell_signal": "MANTENER",
            "classification": "PRECIO_JUSTO",
            "risk_level": "MEDIO",
            "technical_trend": "ALCISTA",
            "missing_data_impact": "BAJO",
            "final_score": "72.5",
            "sell_score": "20.0",
            "margin_of_safety_pct": "0.12",
            "last_relevant_change_date": "2026-01-02",
            "last_relevant_change_type": "SIGNAL_CHANGED",
            "days_in_current_status": "1",
            "days_since_last_relevant_change": "0",
        }
    ],
    "company_status_changes.csv": [
        {
            "analysis_date": "2026-01-02",
            "ticker": "AAPL",
            "change_type": "SIGNAL_CHANGED",
            "previous_company_status": "MANTENER",
            "company_status": "OBSERVAR_COMPRA",
            "previous_classification": "PRECIO_JUSTO",
            "classification": "PRECIO_JUSTO",
            "previous_risk_level": "MEDIO",
            "risk_level": "MEDIO",
            "previous_technical_trend": "NEUTRAL",
            "technical_trend": "ALCISTA",
            "final_score_change": "5.0",
            "margin_of_safety_change": "0.02",
            "price_change_since_previous_status": "0.01",
            "status_reason": "Fixture CI",
        }
    ],
    "portfolio_signal_backtest.csv": [
        {
            "analysis_date": "2025-10-01",
            "ticker": "AAPL",
            "signal": "COMPRAR_OBSERVAR",
            "sell_signal": "MANTENER",
            "classification": "PRECIO_JUSTO",
            "last_close": "180.0",
            "final_score": "70.0",
            "sell_score": "15.0",
            "margin_of_safety_pct": "0.1",
            "risk_level": "MEDIO",
            "technical_trend": "ALCISTA",
            "forward_return_20d": "0.03",
            "forward_return_60d": "0.08",
            "signal_success_60d": "true",
            "backtest_status": "COMPLETO",
        }
    ],
    "portfolio_summary.csv": [{"analysis_date": "2026-01-02", "assets": "1"}],
    "portfolio_ai_summary.csv": [
        {
            "analysis_date": "2026-01-02",
            "summary_type": "daily",
            "alert_title": "Resumen diario fixture",
            "discord_summary": "Discord fixture",
            "dashboard_summary": "Dashboard fixture",
            "top_opportunities": "AAPL",
            "overvalued_summary": "Sin sobrevaloradas",
            "risk_summary": "Riesgo medio",
            "full_report": "Reporte completo fixture",
            "alert_body": "Alerta fixture",
            "alert_sent": "false",
            "alert_error": "",
            "created_at": "2026-01-02T22:00:00Z",
        },
        {
            "analysis_date": "2026-01-02",
            "summary_type": "weekly",
            "alert_title": "Resumen semanal fixture",
            "discord_summary": "Discord semanal fixture",
            "dashboard_summary": "Dashboard semanal fixture",
            "top_opportunities": "AAPL",
            "overvalued_summary": "Sin sobrevaloradas",
            "risk_summary": "Riesgo medio",
            "full_report": "Reporte semanal completo fixture",
            "alert_body": "Alerta semanal fixture",
            "alert_sent": "false",
            "alert_error": "",
            "created_at": "2026-01-02T23:00:00Z",
        },
    ],
    "data_quality_latest.csv": [
        {
            "run_date": "2026-01-02",
            "pipeline": "daily_stocks",
            "ticker": "AAPL",
            "data_status": "OK",
            "severity": "INFO",
            "rows_loaded": "1",
            "analysis_impact": "BAJO",
            "message": "Fixture CI",
        }
    ],
    "ai_analysis_latest.csv": [
        {
            "ticker": "AAPL",
            "ai_final_alert_action": "ENVIAR_COMPRA",
            "ai_summary": "Resumen IA fixture",
            "ai_opportunity": "Oportunidad IA fixture",
            "ai_analysis": "Analisis IA fixture",
            "ai_fair_value_view": "Valor justo IA fixture",
            "ai_technical_view": "Tecnica IA fixture",
            "ai_risks": "Riesgos IA fixture",
            "ai_sell_thesis": "Venta IA fixture",
            "ai_sell_reasons": "Razones IA fixture",
            "ai_sell_price_view": "Precio venta IA fixture",
            "ai_decision_support": "Decision IA fixture",
            "ai_sell_decision_support": "Decision venta IA fixture",
            "data_discrepancies": "Sin discrepancias",
            "external_context_summary": "Contexto IA fixture",
        }
    ],
}

_sell_row = FIXTURES["portfolio_latest.csv"][0].copy()
_sell_row.update(
    {
        "ticker": "MSFT",
        "signal": "VENDER_OBSERVAR",
        "sell_signal": "VENTA_CLARA",
        "classification": "SOBREVALORADA",
        "final_score": "35.0",
        "sell_score": "82.0",
        "margin_of_safety_pct": "-0.18",
        "last_close": "450.0",
        "suggested_buy_price": "360.0",
        "suggested_sell_price": "430.0",
        "risk_level": "ALTO",
        "technical_trend": "BAJISTA",
        "ai_sell_thesis": "Tesis de venta fixture",
    }
)
FIXTURES["portfolio_latest.csv"].append(_sell_row)


def write_fixtures(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in sorted(FIXTURES.items()):
        if not rows:
            raise ValueError(f"fixture {name} must contain at least one row")
        columns = list(rows[0])
        if any(list(row) != columns for row in rows):
            raise ValueError(f"fixture {name} has inconsistent columns")
        path = output_dir / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dashboard/data"))
    args = parser.parse_args()
    write_fixtures(args.output)
    print(f"DASHBOARD_FIXTURES_READY files={len(FIXTURES)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
