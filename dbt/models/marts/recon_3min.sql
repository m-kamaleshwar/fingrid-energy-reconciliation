-- Energy balance for every 3-minute slot:
--   difference = (production - net exports) - consumption
-- Missing inputs give a NULL difference, never a false one.
with pivoted as (
    select
        start_time,
        max(case when name = 'production'  then value end)  as production,
        max(case when name = 'consumption' then value end)  as consumption,
        max(case when name = 'north_swed'  then value end)  as north_swed,
        max(case when name = 'cent_swed'   then value end)  as cent_swed,
        max(case when name = 'estonia'     then value end)  as estonia,
        max(case when name = 'norway'      then value end)  as norway,
        max(case when name = 'production'  then status end) as production_status
    from {{ ref('int_readings_3min') }}
    group by start_time
),
joined as (
    select
        g.start_time,
        g.end_time,
        p.production, p.consumption,
        p.north_swed, p.cent_swed, p.estonia, p.norway,
        p.production_status,
        p.north_swed + p.cent_swed + p.estonia + p.norway as net_exports
    from {{ ref('int_time_grid_3min') }} as g
    left join pivoted as p
        on p.start_time = g.start_time
)
select
    *,
    production - net_exports                 as reconciled,
    (production - net_exports) - consumption as difference,
    case when production is null or production = 0 then null
         else abs((production - net_exports) - consumption) / production * 100
    end                                      as difference_percent
from joined
