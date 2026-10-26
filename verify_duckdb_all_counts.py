import duckdb

con = duckdb.connect("fingrid.duckdb", read_only=True)

slot_count = con.execute("""
    select count(*)
    from recon_3min
""").fetchone()[0]

missing_production = con.execute("""
    select count(*)
    from recon_3min
    where production is null
""").fetchone()[0]

missing_consumption = con.execute("""
    select count(*)
    from recon_3min
    where consumption is null
""").fetchone()[0]

tolerance_failures = con.execute("""
    select count(*)
    from recon_3min
    where difference_percent > 0.5
""").fetchone()[0]

max_abs_difference = con.execute("""
    select max(abs(difference))
    from recon_3min
""").fetchone()[0]

print(f"Slots in recon_3min      : {slot_count}")
print(f"Production missing       : {missing_production}")
print(f"Consumption missing      : {missing_consumption}")
print(f"Tolerance failures       : {tolerance_failures}")
print(f"Max absolute difference  : {max_abs_difference:.3f}")