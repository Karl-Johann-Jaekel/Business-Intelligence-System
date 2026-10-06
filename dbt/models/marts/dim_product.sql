select
    product_id,
    'product:' || product_id as entity_id,
    category_name_pt,
    category_name_en,
    'category:' || category_name_en as category_entity_id,
    photos_qty,
    weight_g,
    length_cm,
    height_cm,
    width_cm
from {{ ref('int_products__categorized') }}
