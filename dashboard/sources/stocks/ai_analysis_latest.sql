select
  *
from `stocks-437902.acciones_dataset.portfolio_ai_analysis_daily`
where analysis_date = (
  select max(analysis_date)
  from `stocks-437902.acciones_dataset.portfolio_ai_analysis_daily`
)
