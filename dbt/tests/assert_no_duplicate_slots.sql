-- Each dataset must have at most one reading per 3-minute slot
select name, start_time, count(*) as copies
from {{ ref('int_readings_3min') }}
group by name, start_time
having count(*) > 1
