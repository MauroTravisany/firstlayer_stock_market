---
title: Calidad de datos
---

```sql quality
select
  *
from stocks.data_quality_latest
order by run_date desc, pipeline, ticker
```

```sql quality_summary
select
  pipeline,
  data_status,
  count(*) as registros
from stocks.data_quality_latest
group by pipeline, data_status
order by pipeline, data_status
```

# Calidad de datos

<BarChart data={quality_summary} x=pipeline y=registros series=data_status/>

<DataTable data={quality} rows=50/>
