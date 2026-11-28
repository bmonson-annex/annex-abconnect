"""Lot-number spelling at the transport boundary; identifiers are independent."""

import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from ab.api.endpoints.catalog import CatalogEndpoint
from ab.api.endpoints.lots import LotsEndpoint
from ab.api.models.catalog import BulkUpsertRequest
from ab.api.models.lots import AddLotRequest, LotCatalogDto, LotDto, normalize_lot_number
from tests.conftest import REQUESTS_DIR


def bulk_body():
    return json.loads((REQUESTS_DIR / "BulkUpsertRequest.json").read_text())


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0000"), ("0", "0000"), ("0417", "0417"), ("7b", "0007B"), ("0100A", "0100A"),
     (" 7B ", "0007B"), ("00123", "0123"), ("000000", "0000"), (9999, "9999")],
)
def test_normalize_auction_lot_number(value, expected):
    assert normalize_lot_number(value) == normalize_lot_number(expected) == expected


@pytest.mark.parametrize("invalid", [None, True, "", "A1", "1BC", "1.0", -1, 10000, "１００", "3ß", 1.5])
def test_invalid_number_does_not_write(invalid):
    transport = Mock()
    payload = bulk_body()
    payload["catalogs"][0]["lots"][0]["lotNumber"] = invalid
    with pytest.raises(ValidationError):
        CatalogEndpoint(transport).bulk_upsert(data=payload)
    transport.request.assert_not_called()


@pytest.mark.parametrize("as_model", [False, True])
def test_bulk_transport_preserves_ids_and_formats_only_auction_numbers(as_model):
    payload = bulk_body()
    catalog = payload["catalogs"][0]
    catalog["customerCatalogId"] = "007"
    catalog["lots"] = [
        {"lotNumber": "0417", "customerItemId": "007", "data": {}},
        {"lotNumber": "7b", "customerItemId": "7b", "data": {}},
    ]
    other = deepcopy(catalog)
    other["customerCatalogId"] = "0007"
    payload["catalogs"].append(other)
    transport = Mock()
    transport.request.return_value = []
    CatalogEndpoint(transport).bulk_upsert(data=BulkUpsertRequest.model_validate(payload) if as_model else payload)
    sent = transport.request.call_args.kwargs["json"]["catalogs"]
    assert [c["customerCatalogId"] for c in sent] == ["007", "0007"]
    for entry in sent:
        assert [(r["customerItemId"], r["lotNumber"]) for r in entry["lots"]] == [("007", "0417"), ("7b", "0007B")]


@pytest.mark.parametrize("separate_entries", [False, True])
def test_canonical_collision_in_a_catalog_fails_before_request(separate_entries):
    payload = bulk_body()
    lots = payload["catalogs"][0]["lots"]
    duplicate = {**lots[0], "lotNumber": "0001", "customerItemId": "second-item"}
    if separate_entries:
        payload["catalogs"].append({**payload["catalogs"][0], "lots": [duplicate]})
    else:
        lots.append(duplicate)
    transport = Mock()
    with pytest.raises(ValidationError, match="duplicate lot number 0001"):
        CatalogEndpoint(transport).bulk_upsert(data=payload)
    transport.request.assert_not_called()


def test_add_and_read_have_separate_spelling_rules():
    association = LotCatalogDto(catalogId=3, lotNumber="7b")
    transport = Mock()
    transport.request.return_value = {"id": 22, "catalogs": [{"catalogId": 3, "lotNumber": "7b"}]}
    result = LotsEndpoint(transport).create(data=AddLotRequest(catalogs=[association]))
    assert transport.request.call_args.kwargs["json"]["catalogs"] == [{"catalogId": 3, "lotNumber": "0007B"}]
    assert result.catalogs[0].lot_number == association.lot_number == "7b"


def test_targeted_update_preserves_other_associations_and_external_ids():
    transport = Mock()
    transport.request.return_value = None
    lot = LotDto.model_validate({"id": 22, "catalogs": [{"catalogId": 3, "lotNumber": "7b"},
                                                        {"catalogId": 4, "lotNumber": "42"}],
                                 "platforms": [{"platformId": 11, "platformItemId": "007"}]})
    lot.catalogs[0].lot_number = normalize_lot_number(lot.catalogs[0].lot_number)
    LotsEndpoint(transport).update(lot.id, data={"catalogs": lot.catalogs, "platforms": lot.platforms})
    transport.request.assert_called_once_with("PUT", "/Lot/22", json={
        "catalogs": [{"catalogId": 3, "lotNumber": "0007B"}, {"catalogId": 4, "lotNumber": "42"}],
        "platforms": [{"platformId": 11, "platformItemId": "007"}],
    })
