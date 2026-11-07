"""Unit tests for the datasource, connection and calculated-field parser."""

from __future__ import annotations

from tableau_qc.parsers.datasource_parser import DataSourceParser
from tableau_qc.xmlio.loader import load_xml_bytes


def _parse(xml: bytes):
    document = load_xml_bytes(xml)
    return DataSourceParser(document).parse_all(document.root)


SQLSERVER = """<datasource caption='Sales' inline='true' name='federated.sales' version='18.1'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='db' name='sqlserver.1'>
            <connection class='sqlserver' dbname='analytics' server='db.internal' username='svc' />
          </named-connection>
        </named-connections>
        {relation}
      </connection>
      {extract}
      <column caption='Profit Ratio' datatype='real' name='[Calculation_1]' role='measure'>
        <calculation class='tableau' formula='SUM([Profit])/SUM([Sales])' />
      </column>
      <column caption='Sales' datatype='real' name='[Sales]' role='measure' />
    </datasource>"""


def _workbook(relation="<relation name='t' table='[dbo].[t]' type='table' />", extract=""):
    return (
        "<workbook><datasources>"
        + SQLSERVER.format(relation=relation, extract=extract)
        + "</datasources></workbook>"
    ).encode()


def test_basic_attributes():
    datasource = _parse(_workbook())[0]
    assert datasource.name == "federated.sales"
    assert datasource.caption == "Sales"
    assert datasource.is_inline is True
    assert datasource.is_parameters is False
    assert datasource.column_count == 2


def test_federated_wrapper_is_excluded_from_connections():
    datasource = _parse(_workbook())[0]
    assert datasource.connection_classes == ["sqlserver"]
    assert datasource.connections[0].dbname == "analytics"
    assert datasource.connections[0].server == "db.internal"
    assert datasource.connections[0].username == "svc"


def test_custom_sql_is_detected_under_the_federated_connection():
    """Tableau stores <relation type='text'> on the federated wrapper."""
    relation = "<relation name='Custom SQL Query' type='text'>SELECT 1</relation>"
    datasource = _parse(_workbook(relation=relation))[0]
    assert datasource.uses_custom_sql is True


def test_table_relations_are_not_custom_sql():
    assert _parse(_workbook())[0].uses_custom_sql is False


def test_extract_detected_from_element():
    datasource = _parse(_workbook(extract="<extract enabled='true' />"))[0]
    assert datasource.has_extract is True


def test_extract_detected_from_hyper_connection():
    xml = b"""<workbook><datasources>
      <datasource name='ds'><connection class='hyper' dbname='x.hyper' /></datasource>
    </datasources></workbook>"""
    assert _parse(xml)[0].has_extract is True


def test_live_connection_has_no_extract():
    assert _parse(_workbook())[0].has_extract is False


def test_calculated_fields_are_parsed():
    datasource = _parse(_workbook())[0]
    assert len(datasource.calculated_fields) == 1
    calculation = datasource.calculated_fields[0]
    assert calculation.caption == "Profit Ratio"
    assert calculation.formula == "SUM([Profit])/SUM([Sales])"
    assert calculation.datasource == "federated.sales"
    assert calculation.is_parameter is False
    assert calculation.source.attribute == "formula"


def test_plain_columns_are_not_calculated_fields():
    assert all(c.name != "[Sales]" for c in _parse(_workbook())[0].calculated_fields)


def test_parameters_datasource_is_flagged():
    xml = b"""<workbook><datasources>
      <datasource hasconnection='false' inline='true' name='Parameters'>
        <column caption='Top N' datatype='integer' name='[Parameter 1]' param-domain-type='range'>
          <calculation class='tableau' formula='5' />
        </column>
      </datasource>
    </datasources></workbook>"""
    datasource = _parse(xml)[0]
    assert datasource.is_parameters is True
    assert datasource.calculated_fields[0].is_parameter is True


def test_non_tableau_calculations_are_skipped():
    xml = b"""<workbook><datasources><datasource name='ds'>
      <column name='[c]'><calculation class='categorical-bin' /></column>
    </datasource></datasources></workbook>"""
    assert _parse(xml)[0].calculated_fields == []


def test_missing_datasources_section_returns_empty():
    document = load_xml_bytes(b"<workbook />")
    assert DataSourceParser(document).parse_all(document.root) == []


def test_real_workbook_datasources(new_workbook_xml_path):
    from conftest import parse_fixture

    workbook = parse_fixture(new_workbook_xml_path)
    assert len(workbook.datasources) == 3
    assert workbook.uses_custom_sql is True
    # The custom SQL sits inside an extract, so it is not a live-connection risk.
    assert workbook.live_custom_sql_datasources == []
