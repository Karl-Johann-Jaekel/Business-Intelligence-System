-- Budgets are synthetic (controlling workbook), actuals are real Olist GMV.
with clock as (
    select sim_date from {{ ref('stg_ops__sim_clock') }}
),

actual as (
    select
        date_trunc('month', purchase_date)::date as month_start,
        category_name_en,
        sum(price) as actual_gmv
    from {{ ref('fct_order_items') }}
    where not is_canceled
    group by 1, 2
)

select
    b.budget_month as month_start,
    b.category_name_en,
    'category:' || b.category_name_en as entity_id,
    b.budget_brl,
    coalesce(a.actual_gmv, 0) as actual_gmv,
    coalesce(a.actual_gmv, 0) - b.budget_brl as deviation_abs,
    round((coalesce(a.actual_gmv, 0) - b.budget_brl) / nullif(b.budget_brl, 0), 6) as deviation_rate,
    (b.budget_month + interval '1 month' - interval '1 day')::date <= c.sim_date as is_complete
from {{ ref('stg_controlling__budgets') }} b
cross join clock c
left join actual a
    on a.month_start = b.budget_month and a.category_name_en = b.category_name_en
where b.budget_month <= c.sim_date
