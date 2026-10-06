with daily as (
    {{ latest_per_key(source('marketing', 'daily'), ['date', 'channel']) }}
)

select
    date::date as marketing_date,
    channel,
    sessions::int as sessions,
    ad_spend::numeric(12, 2) as ad_spend
from daily
