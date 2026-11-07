"""Datasource, connection and calculated-field parsing."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List

from ..domain.models import CalculatedField, DataSource, DataSourceConnection
from .base import BaseParser

#: Datasource name Tableau reserves for workbook parameters.
PARAMETERS_DATASOURCE = "Parameters"


class DataSourceParser(BaseParser):
    """Parses ``/workbook/datasources/datasource`` elements."""

    def parse_all(self, root: ET.Element) -> List[DataSource]:
        container = root.find("datasources")
        if container is None:
            return []
        return [self.parse(el) for el in container.findall("datasource")]

    def parse(self, element: ET.Element) -> DataSource:
        name = self.attr(element, "name") or ""
        datasource = DataSource(
            name=name,
            caption=self.attr(element, "caption"),
            is_inline=self.bool_attr(element, "inline"),
            has_connection=self.bool_attr(element, "hasconnection"),
            is_parameters=name == PARAMETERS_DATASOURCE,
            has_extract=self._has_extract(element),
            source=self.ref(element, "name"),
        )
        datasource.connections = self._parse_connections(element)
        columns = element.findall("column")
        datasource.column_count = len(columns)
        datasource.calculated_fields = self._parse_calculated_fields(columns, datasource)
        return datasource

    def _has_extract(self, element: ET.Element) -> bool:
        """True when the datasource is materialised as a Hyper extract."""
        for extract in element.iter("extract"):
            if self.bool_attr(extract, "enabled") is not False:
                return True
        return any(
            connection.get("class") in ("hyper", "dataengine")
            for connection in element.iter("connection")
        )

    def _parse_connections(self, element: ET.Element) -> List[DataSourceConnection]:
        """Physical connections, excluding the federated wrapper.

        Custom SQL is detected at datasource level: Tableau stores
        ``<relation type='text'>`` under the federated connection, not under
        the physical one, so a per-connection scan would always miss it.
        """
        has_custom_sql = any(
            relation.get("type") == "text" for relation in element.iter("relation")
        )
        connections: List[DataSourceConnection] = []
        for connection in element.iter("connection"):
            connection_class = self.attr(connection, "class")
            if connection_class in (None, "federated"):
                continue
            connections.append(
                DataSourceConnection(
                    connection_class=connection_class,
                    dbname=self.attr(connection, "dbname"),
                    server=self.attr(connection, "server"),
                    username=self.attr(connection, "username"),
                    has_custom_sql=has_custom_sql,
                    source=self.ref(connection, "class"),
                )
            )
        return connections

    def _parse_calculated_fields(
        self, columns: List[ET.Element], datasource: DataSource
    ) -> List[CalculatedField]:
        fields: List[CalculatedField] = []
        for column in columns:
            calculation = column.find("calculation")
            if calculation is None or calculation.get("class") != "tableau":
                continue
            formula = calculation.get("formula")
            if formula is None:
                continue
            is_parameter = datasource.is_parameters or column.get("param-domain-type") is not None
            fields.append(
                CalculatedField(
                    name=self.attr(column, "name") or "",
                    caption=self.attr(column, "caption"),
                    formula=formula,
                    datasource=datasource.name,
                    datatype=self.attr(column, "datatype"),
                    role=self.attr(column, "role"),
                    is_parameter=is_parameter,
                    source=self.ref(calculation, "formula"),
                )
            )
        return fields
