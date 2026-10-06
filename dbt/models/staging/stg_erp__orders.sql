-- Olist only provides the final order state. Timestamps after the simulation date are
-- masked and the status is rolled back accordingly, so the replay does not leak the future.
with orders as (
    {{ latest_per_key(source('erp', 'orders'), ['order_id']) }}
),

clock as (
    select sim_date from {{ ref('stg_ops__sim_clock') }}
),

typed as (
    select
        o.order_id,
        o.customer_id,
        o.order_status as final_status,
        o.order_purchase_timestamp::timestamp as purchased_at,
        o.order_approved_at::timestamp as approved_at,
        o.order_delivered_carrier_date::timestamp as delivered_carrier_at,
        o.order_delivered_customer_date::timestamp as delivered_customer_at,
        o.order_estimated_delivery_date::timestamp as estimated_delivery_at,
        c.sim_date
    from orders o
    cross join clock c
),

masked as (
    select
        order_id,
        customer_id,
        final_status,
        purchased_at,
        case when approved_at < sim_date + 1 then approved_at end as approved_at,
        case when delivered_carrier_at < sim_date + 1 then delivered_carrier_at end as delivered_carrier_at,
        case when delivered_customer_at < sim_date + 1 then delivered_customer_at end as delivered_customer_at,
        estimated_delivery_at
    from typed
)

select
    order_id,
    customer_id,
    case
        when final_status = 'delivered' and delivered_customer_at is null
            then case when delivered_carrier_at is not null then 'shipped' else 'processing' end
        else final_status
    end as order_status,
    purchased_at,
    purchased_at::date as purchase_date,
    approved_at,
    delivered_carrier_at,
    delivered_customer_at,
    estimated_delivery_at
from masked
