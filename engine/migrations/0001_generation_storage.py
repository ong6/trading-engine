"""Register the revision-16 generation storage contract without catalog DDL."""

MIGRATION_ID = 1
DESCRIPTION = "revision-16 pinned generation storage contract"
STATEMENTS: tuple[str, ...] = ()
EXPECTED_CATALOG_SHA256 = "dcd1a8ea73f4136bc935f37d506b16b0d65f7928c88788c96a0f2bde809165b7"

