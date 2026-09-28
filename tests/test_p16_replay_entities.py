"""W4 record-to-security mapping is conservative and deterministic."""
from datetime import date, datetime, timezone

from farm.replay.entities import build_name_index, match_securities, normalize_name

TABLE = [
    {"security_id": "S-AAPL", "ticker": "AAPL", "name": "Apple Inc.", "aliases": ("Apple Computer",)},
    {"security_id": "S-GART", "ticker": "IT", "name": "Gartner, Inc.", "aliases": ()},
    {"security_id": "S-C3AI", "ticker": "AI", "name": "C3.ai, Inc.", "aliases": ()},
    {"security_id": "S-HD", "ticker": "HD", "name": "The Home Depot, Inc.", "aliases": ()},
    {"security_id": "S-BRK", "ticker": "BRK.B", "name": "Berkshire Hathaway Holdings", "aliases": ()},
    {"security_id": "S-X", "ticker": "X", "name": "X Corp", "aliases": ()},
    {"security_id": "S-TGT", "ticker": "TGT", "name": "Target Corporation", "aliases": ()},
    {"security_id": "S-FB", "ticker": "FB", "name": "Facebook Platforms Inc",
     "valid_to": date(2021, 10, 28)},
    {"security_id": "S-FB", "ticker": "META", "name": "Meta Platforms Inc",
     "valid_from": "2021-10-28"},
]


def _match(headline="", body="", organizations="", available_at_replay=None):
    return match_securities({
        "headline": headline, "body": body, "organizations": organizations,
        "available_at_replay": available_at_replay,
    }, TABLE)


def test_names_strip_legal_suffixes_and_match_on_word_boundaries():
    assert normalize_name("The Home Depot, Inc.") == "home depot"
    assert normalize_name("Berkshire Hathaway Holdings plc") == "berkshire hathaway"
    assert _match("Shares of home depot and Berkshire Hathaway rose") == ("S-BRK", "S-HD")
    assert _match("Pineapple growers and Applebee's diners") == ()
    assert _match(body="Apple Computer was renamed") == ("S-AAPL",)


def test_one_word_names_never_match_free_text():
    assert _match("Target raised prices") == ()
    assert _match("Apple Inc. beats estimates") == ()
    assert _match("Apple pie recipes") == ()
    assert _match("Target raised prices, $TGT fell") == ("S-TGT",)
    assert _match("Target (NYSE: TGT) raised prices") == ("S-TGT",)
    assert _match(organizations="TARGET,40") == ("S-TGT",)


def test_bare_ticker_words_never_match_only_cashtags_and_exchange_tags():
    assert _match("IT spending and AI models lift X factor for HD screens") == ()
    assert _match("Analysts like $IT and $AI today") == ("S-C3AI", "S-GART")
    assert _match("Gartner (NYSE: IT) reported; Berkshire (NYSE: BRK.B) too") == ("S-BRK", "S-GART")
    assert _match("Unknown (NASDAQ: ZZZZ) and $ZZZZ") == ()
    assert _match("price was US$5 and it cost $X") == ("S-X",)


def test_renamed_issuer_maps_only_inside_each_name_validity_window():
    utc_next_day = datetime(2021, 10, 28, 3, tzinfo=timezone.utc)  # still 10-27 in New York
    old_day = "2021-10-27T20:00:00Z"
    assert _match("Facebook Platforms slips", available_at_replay=old_day) == ("S-FB",)
    assert _match("Meta Platforms slips", available_at_replay=old_day) == ()
    assert _match("Facebook Platforms slips", available_at_replay=utc_next_day) == ()
    assert _match("Meta Platforms slips", available_at_replay=utc_next_day) == ("S-FB",)
    assert _match("$FB and $META", available_at_replay=old_day) == ("S-FB",)
    assert _match("Meta Platforms slips", available_at_replay=date(2021, 1, 4)) == ()
    # No availability date: no window filter.
    assert _match("Facebook Platforms and Meta Platforms") == ("S-FB",)


def test_gkg_organizations_and_determinism():
    assert _match(organizations="apple inc,120;gartner,300;it,5") == ("S-AAPL", "S-GART")
    index = build_name_index(TABLE)
    record = {"headline": "Apple Computer and Gartner (NYSE: IT)", "body": None}
    assert match_securities(record, index) == ("S-AAPL", "S-GART")
    assert match_securities(record, index) == match_securities(record, list(reversed(TABLE)))
    assert match_securities({"headline": ""}, index) == ()
