with sellers as (
    {{ latest_per_key(source('erp', 'sellers'), ['seller_id']) }}
)

select
    seller_id,
    seller_zip_code_prefix as zip_code_prefix,
    seller_city as city,
    upper(trim(seller_state)) as state_code
from sellers
