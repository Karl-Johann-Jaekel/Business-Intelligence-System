with products as (
    {{ latest_per_key(source('erp', 'products'), ['product_id']) }}
)

select
    product_id,
    product_category_name as category_name_pt,
    product_photos_qty::int as photos_qty,
    product_weight_g::numeric as weight_g,
    product_length_cm::numeric as length_cm,
    product_height_cm::numeric as height_cm,
    product_width_cm::numeric as width_cm
from products
