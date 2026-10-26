-- Slots where the balance doesn't close within tolerance.
-- Real data has genuine breaches (about 1% of slots), so this warns and
-- stores the failing rows for investigation instead of failing the build.
{{ config(severity='warn', store_failures=true) }}

select start_time, production, consumption, net_exports, difference, difference_percent
from {{ ref('recon_3min') }}
where difference_percent > {{ var('tolerance_pct') }}
