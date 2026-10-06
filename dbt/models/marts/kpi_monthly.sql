with clock as (
    select sim_date from {{ ref('stg_ops__sim_clock') }}
),

from_daily as (
    select
        date_trunc('month', kpi_date)::date as month_start,
        kpi_key,
        dimension,
        dimension_value,
        entity_id,
        aggregation,
        sum(numerator) as numerator,
        sum(denominator) as denominator
    from {{ ref('kpi_daily') }}
    group by 1, 2, 3, 4, 5, 6
),

budget as (
    select
        month_start,
        'budget_deviation' as kpi_key,
        case when grouping(category_name_en) = 0 then 'category' else 'total' end as dimension,
        case when grouping(category_name_en) = 0 then category_name_en else 'all' end as dimension_value,
        case
            when grouping(category_name_en) = 0 then 'category:' || category_name_en
            else 'kpi:budget_deviation'
        end as entity_id,
        'ratio' as aggregation,
        sum(deviation_abs) as numerator,
        sum(budget_brl) as denominator
    from {{ ref('budget_vs_actual') }}
    group by grouping sets ((month_start), (month_start, category_name_en))
),

combined as (
    select * from from_daily
    union all
    select * from budget
)

select
    m.month_start,
    m.kpi_key,
    m.dimension,
    m.dimension_value,
    m.entity_id,
    case
        when m.aggregation = 'sum' then m.numerator
        else round(m.numerator / nullif(m.denominator, 0), 6)
    end as value,
    m.numerator,
    m.denominator,
    m.aggregation,
    (m.month_start + interval '1 month' - interval '1 day')::date <= c.sim_date as is_complete
from combined m
cross join clock c
