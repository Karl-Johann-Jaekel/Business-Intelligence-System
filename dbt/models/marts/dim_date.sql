select
    d::date as date_day,
    extract(isodow from d)::int as iso_weekday,
    to_char(d, 'Dy') as weekday_name,
    extract(isodow from d) in (6, 7) as is_weekend,
    date_trunc('week', d)::date as week_start,
    date_trunc('month', d)::date as month_start,
    extract(year from d)::int as year,
    extract(quarter from d)::int as quarter,
    extract(month from d)::int as month
from generate_series('2016-01-01'::date, '2019-12-31'::date, interval '1 day') as d
