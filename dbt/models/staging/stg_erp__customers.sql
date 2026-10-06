with customers as (
    {{ latest_per_key(source('erp', 'customers'), ['customer_id']) }}
)

select
    customer_id,
    customer_unique_id,
    customer_zip_code_prefix as zip_code_prefix,
    customer_city as city,
    upper(trim(customer_state)) as state_code
from customers
