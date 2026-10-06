with orders as (
    select * from {{ ref('stg_erp__orders') }}
),

customers as (
    select * from {{ ref('stg_erp__customers') }}
),

items as (
    select
        order_id,
        count(*) as items_count,
        sum(price) as items_value,
        sum(freight_value) as freight_value
    from {{ ref('stg_erp__order_items') }}
    group by order_id
),

payments as (
    select order_id, sum(payment_value) as payment_value
    from {{ ref('stg_erp__payments') }}
    group by order_id
)

select
    o.order_id,
    o.customer_id,
    c.customer_unique_id,
    c.state_code as customer_state,
    o.order_status,
    o.order_status in ('canceled', 'unavailable') as is_canceled,
    o.purchased_at,
    o.purchase_date,
    o.approved_at,
    o.delivered_carrier_at,
    o.delivered_customer_at,
    o.delivered_customer_at::date as delivery_date,
    o.estimated_delivery_at,
    round((extract(epoch from o.delivered_customer_at - o.purchased_at) / 86400.0)::numeric, 3) as delivery_days,
    case
        when o.delivered_customer_at is not null
            then o.delivered_customer_at::date <= o.estimated_delivery_at::date
    end as is_on_time,
    row_number() over (
        partition by c.customer_unique_id order by o.purchased_at, o.order_id
    ) = 1 as is_first_order,
    coalesce(i.items_count, 0) as items_count,
    coalesce(i.items_value, 0) as items_value,
    coalesce(i.freight_value, 0) as freight_value,
    coalesce(p.payment_value, 0) as payment_value
from orders o
join customers c using (customer_id)
left join items i using (order_id)
left join payments p using (order_id)
