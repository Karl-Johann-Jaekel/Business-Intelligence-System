-- Single row describing pipeline freshness, so the read-only API needs no access to ops.
select
    c.sim_date,
    (select max(kpi_date) from {{ ref('kpi_daily') }}) as latest_kpi_date,
    (select max(finished_at) from {{ source('ops', 'load_log') }} where status = 'success')
        as last_successful_load_at,
    (select max(finished_at) from {{ source('ops', 'load_log') }} where status = 'failed')
        as last_failed_load_at,
    now() as built_at
from {{ ref('stg_ops__sim_clock') }} c
