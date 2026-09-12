commit a1f3c9e — "loader: read the judgment file with 1-based query ids"
files: data/loader.py (+18 −6), tests/test_loader.py (+34 −0)
The parser was treating the first query id as 0, shifting every judgment by one row.
Test added that asserts the first and last query ids round-trip.
