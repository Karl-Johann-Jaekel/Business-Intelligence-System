select
    month::date as budget_month,
    category as category_name_en,
    budget_brl::numeric(14, 2) as budget_brl
from {{ source('controlling', 'budgets') }}
