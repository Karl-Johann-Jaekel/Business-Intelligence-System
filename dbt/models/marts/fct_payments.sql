select
    p.order_id,
    p.payment_sequential,
    p.payment_type,
    p.payment_installments,
    p.payment_value,
    o.purchase_date
from {{ ref('stg_erp__payments') }} p
join {{ ref('fct_orders') }} o using (order_id)
