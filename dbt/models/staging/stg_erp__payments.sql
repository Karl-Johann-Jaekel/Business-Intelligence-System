with payments as (
    {{ latest_per_key(source('erp', 'payments'), ['order_id', 'payment_sequential']) }}
)

select
    order_id,
    payment_sequential::int as payment_sequential,
    payment_type,
    payment_installments::int as payment_installments,
    payment_value::numeric(12, 2) as payment_value
from payments
