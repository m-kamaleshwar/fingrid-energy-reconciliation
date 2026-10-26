import duckdb
con = duckdb.connect("fingrid.duckdb", read_only=True)
print(con.sql("select * from main_dbt_test__audit.balance_within_tolerance"))