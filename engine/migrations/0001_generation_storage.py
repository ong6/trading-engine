"""Register the revision-16 generation storage contract without catalog DDL."""

MIGRATION_ID = 1
DESCRIPTION = "revision-16 pinned generation storage contract"
STATEMENTS: tuple[str, ...] = ()
EXPECTED_CATALOG_SHA256 = "7286ea9b55c05d1bb16af2f2faeeb6aa69b1d5f711e1219efb2d5c27709a2e5d"
