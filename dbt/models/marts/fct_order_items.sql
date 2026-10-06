select
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    p.category_name_en,
    o.customer_unique_id,
    o.state_code,
    o.purchase_date,
    o.is_canceled,
    i.price,
    i.freight_value
from {{ ref('stg_erp__order_items') }} i
join {{ ref('fct_orders') }} o using (order_id)
join {{ ref('int_products__categorized') }} p using (product_id)
