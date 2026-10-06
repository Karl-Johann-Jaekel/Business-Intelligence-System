with centroids as (
    select state_code, avg(lat) as lat, avg(lng) as lng
    from {{ ref('stg_legacy__geolocation') }}
    -- Olist geodata contains a few points outside Brazil.
    where lat between -34 and 6 and lng between -74 and -34
    group by state_code
)

select
    s.state_code,
    'region:' || s.state_code as entity_id,
    s.state_name,
    s.macro_region,
    round(c.lat::numeric, 4) as centroid_lat,
    round(c.lng::numeric, 4) as centroid_lng
from {{ ref('br_states') }} s
left join centroids c using (state_code)
