with items as (
    {{ latest_per_key(source('erp', 'order_items'), ['order_id', 'order_item_id']) }}
)

select
    order_id,
    order_item_id::int as order_item_id,
    product_id,
    seller_id,
    shipping_limit_date::timestamp as shipping_limit_at,
    price::numeric(12, 2) as price,
    freight_value::numeric(12, 2) as freight_value
from items
