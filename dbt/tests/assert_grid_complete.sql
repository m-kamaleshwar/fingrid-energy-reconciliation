-- The reconciliation must contain exactly one row per expected slot
select count(*) as slots
from {{ ref('recon_3min') }}
having count(*) <> datediff('minute', timestamp '{{ var("start_time") }}',
                                      timestamp '{{ var("end_time") }}') / 3
