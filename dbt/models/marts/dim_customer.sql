-- One row per real customer (Olist issues a new customer_id per order).
with orders as (
    select * from {{ ref('int_orders__enriched') }}
)

select
    customer_unique_id,
    'customer:' || customer_unique_id as entity_id,
    (array_agg(customer_state order by purchased_at desc))[1] as state_code,
    min(purchased_at) as first_order_at,
    max(purchased_at) as last_order_at,
    count(*) as orders_count
from orders
group by customer_unique_id
