select
    r.review_id,
    r.order_id,
    o.state_code,
    r.review_score,
    r.review_date,
    r.created_at
from {{ ref('stg_legacy__reviews') }} r
join {{ ref('fct_orders') }} o using (order_id)
