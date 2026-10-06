-- English category name, falling back to the Portuguese name, then 'unknown'.
-- Mirrors ingestion.setup.synthetic.category_en so budgets match actuals.
select
    p.product_id,
    p.category_name_pt,
    coalesce(t.category_name_en, p.category_name_pt, 'unknown') as category_name_en,
    p.photos_qty,
    p.weight_g,
    p.length_cm,
    p.height_cm,
    p.width_cm
from {{ ref('stg_erp__products') }} p
left join {{ ref('stg_legacy__category_translation') }} t using (category_name_pt)
