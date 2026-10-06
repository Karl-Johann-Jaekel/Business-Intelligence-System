-- review_id is not unique in Olist (one review can cover several orders).
with reviews as (
    {{ latest_per_key(source('legacy', 'reviews'), ['review_id', 'order_id']) }}
)

select
    review_id,
    order_id,
    review_score::int as review_score,
    review_comment_title as comment_title,
    review_comment_message as comment_message,
    review_creation_date::timestamp as created_at,
    review_creation_date::date as review_date,
    review_answer_timestamp::timestamp as answered_at
from reviews
