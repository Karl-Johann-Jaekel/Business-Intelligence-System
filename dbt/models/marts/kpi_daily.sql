-- One row per day, KPI and dimension value. Ratio KPIs carry numerator and denominator so
-- that coarser grains (kpi_monthly) can be re-aggregated correctly.
-- Total rows are zero-filled over the full date range; dimension rows exist only with data.
with clock as (
    select sim_date from {{ ref('stg_ops__sim_clock') }}
),

spine as (
    select d.date_day as kpi_date
    from {{ ref('dim_date') }} d
    cross join clock c
    where d.date_day between (select min(purchase_date) from {{ ref('fct_orders') }}) and c.sim_date
),

orders_agg as (
    select
        purchase_date as kpi_date,
        case when grouping(state_code) = 0 then 'region' else 'total' end as dimension,
        case when grouping(state_code) = 0 then state_code else 'all' end as dimension_value,
        count(*) as orders_all,
        count(*) filter (where not is_canceled) as orders_valid,
        count(*) filter (where is_canceled) as orders_canceled,
        count(*) filter (where is_first_order) as new_customers,
        count(*) filter (where not is_first_order) as returning_customers
    from {{ ref('fct_orders') }}
    group by grouping sets ((purchase_date), (purchase_date, state_code))
),

orders_frame as (
    select
        s.kpi_date, 'total' as dimension, 'all' as dimension_value,
        coalesce(a.orders_all, 0) as orders_all,
        coalesce(a.orders_valid, 0) as orders_valid,
        coalesce(a.orders_canceled, 0) as orders_canceled,
        coalesce(a.new_customers, 0) as new_customers,
        coalesce(a.returning_customers, 0) as returning_customers
    from spine s
    left join orders_agg a on a.kpi_date = s.kpi_date and a.dimension = 'total'
    union all
    select * from orders_agg where dimension <> 'total'
),

items_agg as (
    select
        purchase_date as kpi_date,
        case
            when grouping(state_code) = 0 then 'region'
            when grouping(category_name_en) = 0 then 'category'
            else 'total'
        end as dimension,
        case
            when grouping(state_code) = 0 then state_code
            when grouping(category_name_en) = 0 then category_name_en
            else 'all'
        end as dimension_value,
        sum(price) as gmv,
        sum(freight_value) as freight,
        count(distinct order_id) as orders_with_items
    from {{ ref('fct_order_items') }}
    where not is_canceled
    group by grouping sets ((purchase_date), (purchase_date, state_code), (purchase_date, category_name_en))
),

items_frame as (
    select
        s.kpi_date, 'total' as dimension, 'all' as dimension_value,
        coalesce(a.gmv, 0) as gmv,
        coalesce(a.freight, 0) as freight,
        coalesce(a.orders_with_items, 0) as orders_with_items
    from spine s
    left join items_agg a on a.kpi_date = s.kpi_date and a.dimension = 'total'
    union all
    select * from items_agg where dimension <> 'total'
),

delivery_agg as (
    select
        delivery_date as kpi_date,
        case when grouping(state_code) = 0 then 'region' else 'total' end as dimension,
        case when grouping(state_code) = 0 then state_code else 'all' end as dimension_value,
        sum(delivery_days) as delivery_days_sum,
        count(*) as delivered,
        count(*) filter (where is_on_time) as delivered_on_time
    from {{ ref('fct_orders') }}
    where delivery_date is not null
    group by grouping sets ((delivery_date), (delivery_date, state_code))
),

review_agg as (
    select
        review_date as kpi_date,
        case when grouping(state_code) = 0 then 'region' else 'total' end as dimension,
        case when grouping(state_code) = 0 then state_code else 'all' end as dimension_value,
        sum(review_score) as score_sum,
        count(*) as reviews
    from {{ ref('fct_reviews') }}
    group by grouping sets ((review_date), (review_date, state_code))
),

marketing_frame as (
    select
        marketing_date as kpi_date,
        'total' as dimension,
        'all' as dimension_value,
        sum(sessions) as sessions,
        sum(ad_spend) as ad_spend
    from {{ ref('fct_marketing_daily') }}
    group by marketing_date
),

kpi_inputs as (
    select o.kpi_date, o.dimension, o.dimension_value, k.*
    from orders_frame o
    cross join lateral (values
        ('orders_count', 'sum', o.orders_valid::numeric, null::numeric),
        ('cancellation_rate', 'ratio', o.orders_canceled::numeric, o.orders_all::numeric),
        ('new_customers', 'sum', o.new_customers::numeric, null::numeric),
        ('returning_customers', 'sum', o.returning_customers::numeric, null::numeric)
    ) as k (kpi_key, aggregation, numerator, denominator)

    union all

    select i.kpi_date, i.dimension, i.dimension_value, k.*
    from items_frame i
    cross join lateral (values
        ('gmv', 'sum', i.gmv, null::numeric),
        ('avg_order_value', 'ratio', i.gmv, i.orders_with_items::numeric),
        ('freight_ratio', 'ratio', i.freight, i.gmv)
    ) as k (kpi_key, aggregation, numerator, denominator)
    where not (k.kpi_key = 'avg_order_value' and i.dimension = 'category')

    union all

    select d.kpi_date, d.dimension, d.dimension_value, k.*
    from delivery_agg d
    cross join lateral (values
        ('delivery_time_avg_days', 'ratio', d.delivery_days_sum, d.delivered::numeric),
        ('on_time_rate', 'ratio', d.delivered_on_time::numeric, d.delivered::numeric)
    ) as k (kpi_key, aggregation, numerator, denominator)

    union all

    select r.kpi_date, r.dimension, r.dimension_value,
        'review_score_avg', 'ratio', r.score_sum::numeric, r.reviews::numeric
    from review_agg r

    union all

    select m.kpi_date, m.dimension, m.dimension_value, k.*
    from marketing_frame m
    join orders_frame o using (kpi_date, dimension, dimension_value)
    join items_frame i using (kpi_date, dimension, dimension_value)
    cross join lateral (values
        ('conversion_rate', 'ratio', o.orders_valid::numeric, m.sessions::numeric),
        ('roas', 'ratio', i.gmv, m.ad_spend)
    ) as k (kpi_key, aggregation, numerator, denominator)
)

select
    kpi_date,
    kpi_key,
    dimension,
    dimension_value,
    case dimension
        when 'region' then 'region:' || dimension_value
        when 'category' then 'category:' || dimension_value
        else 'kpi:' || kpi_key
    end as entity_id,
    case
        when aggregation = 'sum' then numerator
        else round(numerator / nullif(denominator, 0), 6)
    end as value,
    numerator,
    denominator,
    aggregation
from kpi_inputs
