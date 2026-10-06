select sim_date
from {{ source('ops', 'sim_clock') }}
where id = 1
