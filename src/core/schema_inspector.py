"""Schema inspection utilities for extracting database metadata."""

from sqlalchemy import Engine, inspect, text
from sqlalchemy.engine.interfaces import (
    ReflectedColumn,
    ReflectedForeignKeyConstraint,
    ReflectedPrimaryKeyConstraint,
)


class SchemaInspector:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._inspector = inspect(engine)

    def get_table_names(self) -> list[str]:
        return self._inspector.get_table_names()

    def get_columns(self, table_name: str) -> list[ReflectedColumn]:
        return self._inspector.get_columns(table_name)

    def get_primary_keys(self, table_name: str) -> ReflectedPrimaryKeyConstraint:
        return self._inspector.get_pk_constraint(table_name)

    def get_foreign_keys(self, table_name: str) -> list[ReflectedForeignKeyConstraint]:
        return self._inspector.get_foreign_keys(table_name)

    def get_sample_values(self, table_name: str, column_name: str, limit: int = 5) -> list:
        sql = text(f"SELECT DISTINCT {column_name} FROM {table_name} LIMIT :limit")
        with self._engine.connect() as conn:
            rows = conn.execute(sql, {"limit": limit}).fetchall()
        return [row[0] for row in rows]

    def get_full_schema(self) -> str:
        lines: list[str] = []
        pk_set: set[str]

        for table_name in self.get_table_names():
            lines.append(f"TABLE: {table_name}")

            pk_info = self.get_primary_keys(table_name)
            pk_set = set(pk_info.get("constrained_columns", []))

            for col in self.get_columns(table_name):
                col_type = str(col["type"])
                suffix = " PRIMARY KEY" if col["name"] in pk_set else ""
                lines.append(f"  {col['name']} {col_type}{suffix}")

            for fk in self.get_foreign_keys(table_name):
                local_cols = ", ".join(fk["constrained_columns"])
                ref_table = fk["referred_table"]
                ref_cols = ", ".join(fk["referred_columns"])
                lines.append(f"  FK: {local_cols} -> {ref_table}({ref_cols})")

            lines.append("")

        return "\n".join(lines).rstrip()

    def get_table_detail(self, table_name: str) -> str:
        lines: list[str] = [f"TABLE: {table_name}"]

        pk_info = self.get_primary_keys(table_name)
        pk_set = set(pk_info.get("constrained_columns", []))

        lines.append("  Columns:")
        for col in self.get_columns(table_name):
            col_type = str(col["type"])
            pk_marker = " [PK]" if col["name"] in pk_set else ""
            nullable = "" if col["nullable"] else " NOT NULL"
            sample = self.get_sample_values(table_name, col["name"])
            sample_str = f"  samples={sample}" if sample else ""
            lines.append(f"    {col['name']} {col_type}{pk_marker}{nullable}{sample_str}")

        fks = self.get_foreign_keys(table_name)
        if fks:
            lines.append("  Foreign Keys:")
            for fk in fks:
                local_cols = ", ".join(fk["constrained_columns"])
                ref_table = fk["referred_table"]
                ref_cols = ", ".join(fk["referred_columns"])
                lines.append(f"    {local_cols} -> {ref_table}({ref_cols})")

        return "\n".join(lines)

    def get_tables_with_counts(self) -> list[dict]:
        result = []
        with self._engine.connect() as conn:
            for table_name in self.get_table_names():
                count = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
                result.append({"table_name": table_name, "row_count": count})
        return result

    def get_sample_rows(self, table_name: str, limit: int = 5) -> list[dict]:
        sql = text(f"SELECT * FROM {table_name} LIMIT :limit")
        with self._engine.connect() as conn:
            rows = conn.execute(sql, {"limit": limit}).mappings().all()
        return [dict(row) for row in rows]
