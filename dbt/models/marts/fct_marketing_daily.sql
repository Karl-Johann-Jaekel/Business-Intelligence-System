-- Synthetic source: see docs/kpi-glossary.md.
select
    m.marketing_date,
    m.channel,
    m.sessions,
    m.ad_spend
from {{ ref('stg_marketing__daily') }} m
cross join {{ ref('stg_ops__sim_clock') }} c
where m.marketing_date <= c.sim_date
