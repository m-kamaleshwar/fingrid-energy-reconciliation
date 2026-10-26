-- Every 3-minute reading keeps only its own slot. Records claiming to last
-- longer have an incorrect end time, so they are corrected and labelled.
select
    name,
    start_time,
    start_time + interval 3 minute as end_time,
    value,
    case when end_time - start_time > interval 3 minute
         then 'endtime_fixed' else 'original' end as status
from {{ ref('stg_fingrid_readings') }}
where interval_min = 3
  and start_time >= timestamp '{{ var("start_time") }}'
  and start_time <  timestamp '{{ var("end_time") }}'
