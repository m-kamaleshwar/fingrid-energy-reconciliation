-- Raw readings, labelled with their dataset name and interval
select
    d.name,
    r.dataset_id,
    r.start_time,
    r.end_time,
    r.value,
    d.interval_min
from {{ source('raw', 'fingrid_readings') }} as r
join {{ ref('fingrid_datasets') }} as d
    on r.dataset_id = d.dataset_id
