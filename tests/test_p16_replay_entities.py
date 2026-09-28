"""W4 record-to-security mapping is conservative and deterministic."""
from farm.replay.entities import build_name_index, match_securities, normalize_name

TABLE = [
    {"security_id": "S-AAPL", "ticker": "AAPL", "name": "Apple Inc.", "aliases": ("Apple Computer",)},
    {"security_id": "S-GART", "ticker": "IT", "name": "Gartner, Inc.", "aliases": ()},
    {"security_id": "S-C3AI", "ticker": "AI", "name": "C3.ai, Inc.", "aliases": ()},
    {"security_id": "S-HD", "ticker": "HD", "name": "The Home Depot, Inc.", "aliases": ()},
    {"security_id": "S-BRK", "ticker": "BRK.B", "name": "Berkshire Hathaway Holdings", "aliases": ()},
    {"security_id": "S-X", "ticker": "X", "name": "X Corp", "aliases": ()},
]


def _match(headline="", body="", organizations=""):
    return match_securities({"headline": headline, "body": body, "organizations": organizations}, TABLE)


def test_names_strip_legal_suffixes_and_match_on_word_boundaries():
    assert normalize_name("The Home Depot, Inc.") == "home depot"
    assert normalize_name("Berkshire Hathaway Holdings plc") == "berkshire hathaway"
    assert _match("Apple Inc. beats estimates") == ("S-AAPL",)
    assert _match("Shares of home depot and Berkshire Hathaway rose") == ("S-BRK", "S-HD")
    assert _match("Pineapple growers and Applebee's diners") == ()
    assert _match(body="Apple Computer was renamed") == ("S-AAPL",)


def test_bare_ticker_words_never_match_only_cashtags_and_exchange_tags():
    assert _match("IT spending and AI models lift X factor for HD screens") == ()
    assert _match("apple pie recipes") == ()
    assert _match("Apple pie recipes") == ("S-AAPL",)  # exact alias, proper-noun form: accepted
    assert _match("Analysts like $IT and $AI today") == ("S-C3AI", "S-GART")
    assert _match("Gartner (NYSE: IT) reported; Berkshire (NYSE: BRK.B) too") == ("S-BRK", "S-GART")
    assert _match("Unknown (NASDAQ: ZZZZ) and $ZZZZ") == ()
    assert _match("price was US$5 and it cost $X") == ("S-X",)


def test_gkg_organizations_and_determinism():
    assert _match(organizations="apple inc,120;gartner,300;it,5") == ("S-AAPL", "S-GART")
    index = build_name_index(TABLE)
    record = {"headline": "Apple and Gartner (NYSE: IT)", "body": None}
    assert match_securities(record, index) == match_securities(record, list(reversed(TABLE)))
    assert match_securities({"headline": ""}, index) == ()
