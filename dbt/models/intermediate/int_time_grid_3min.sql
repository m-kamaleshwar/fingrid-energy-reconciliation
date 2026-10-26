-- The expected grid: every 3-minute slot that SHOULD exist in the period
select
    range as start_time,
    range + interval 3 minute as end_time
from range(timestamp '{{ var("start_time") }}',
           timestamp '{{ var("end_time") }}',
           interval 3 minute)
