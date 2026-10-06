select
    geolocation_zip_code_prefix as zip_code_prefix,
    geolocation_lat::double precision as lat,
    geolocation_lng::double precision as lng,
    geolocation_city as city,
    upper(trim(geolocation_state)) as state_code
from {{ source('legacy', 'geolocation') }}
