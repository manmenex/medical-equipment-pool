import pytest

from app.utils.exceptions import MissingColumnsError
from app.utils.excel_mapper import map_columns, validate_mapping


def test_exact_alias_mapping():
    mapping = map_columns(["Asset Number", "Manufacturer", "Model", "Department"])
    assert mapping.field_to_column["asset_number"] == "Asset Number"
    assert mapping.field_to_column["manufacturer"] == "Manufacturer"
    assert mapping.field_to_column["model_number"] == "Model"
    assert mapping.field_to_column["department"] == "Department"
    assert mapping.unmapped_columns == []


def test_fuzzy_mapping_for_slightly_different_headers():
    mapping = map_columns(["Assett #", "Mfr.", "Serial No", "Room"])
    assert mapping.field_to_column.get("asset_number") == "Assett #"
    assert mapping.field_to_column.get("manufacturer") == "Mfr."
    assert mapping.field_to_column.get("serial_number") == "Serial No"
    assert mapping.field_to_column.get("location") == "Room"


def test_unmapped_columns_are_preserved_not_dropped():
    mapping = map_columns(["Asset Number", "Some Custom Hospital Field"])
    assert "Some Custom Hospital Field" in mapping.unmapped_columns


def test_missing_required_column_raises():
    mapping = map_columns(["Manufacturer", "Model"])
    with pytest.raises(MissingColumnsError):
        validate_mapping(mapping)
