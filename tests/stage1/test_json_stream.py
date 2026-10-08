import pytest
from floatchat_core.ingestion.json_stream import documents
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.raw import RawNumber


def test_stream_preserves_decimal_lexemes_and_braces_in_strings():
    rows = list(documents(b'[{"n":1.00e0,"s":"}\\"["},{"n":2}]', number_decoder=RawNumber))
    assert rows[0]["n"].source_token == "1.00e0"
    assert rows[1]["n"] == 2


@pytest.mark.parametrize(
    "raw",
    [b"[{}", b"[{},]", b"[{}]x", b"[{} {}]", b"[{}],[]", b"[", b"[1]", b"{}"],
)
def test_stream_rejects_incomplete_or_noncontract_response(raw):
    with pytest.raises(Rejection):
        list(documents(raw))


def test_stream_bound_checks_before_decoding_extra_profile():
    iterator = documents(b'[{"n":1},{"n":1e100000000}]', max_documents=1)
    assert next(iterator)["n"] == 1
    with pytest.raises(Rejection, match="profile_count_limit"):
        next(iterator)


def test_stream_empty_is_valid_json_but_proves_no_inventory_by_itself():
    assert list(documents(b" \n[]\t")) == []


def test_stream_outer_array_counts_toward_depth_bound():
    raw = b'[{"v":' + b"[" * 30 + b"0" + b"]" * 30 + b"}]"
    assert len(list(documents(raw))) == 1
    with pytest.raises(Rejection, match="json_depth_limit"):
        list(documents(raw.replace(b":", b":[").replace(b"}", b"]}")))
