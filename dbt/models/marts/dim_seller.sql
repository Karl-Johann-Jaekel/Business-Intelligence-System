select
    seller_id,
    'seller:' || seller_id as entity_id,
    city,
    state_code
from {{ ref('stg_erp__sellers') }}
