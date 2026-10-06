{# Keep the most recently loaded raw row per key. #}
{% macro latest_per_key(relation, key_columns) %}
    select * from (
        select *, row_number() over (
            partition by {{ key_columns | join(', ') }} order by _loaded_at desc
        ) as _rn
        from {{ relation }}
    ) ranked
    where _rn = 1
{% endmacro %}
