"""Generate additive migration 002; never rewrite initial schema 001."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable
from app.models import InferenceDecision


def render():
    table = InferenceDecision.__table__
    dialect = mysql.dialect()
    statements = ['-- Migration 002: immutable scope evidence; preserves all existing records.',
                  '-- Apply once in the existing application database before activating the new backend.',
                  'SET NAMES utf8mb4;', "SET time_zone = '+00:00';",
                  str(CreateTable(table).compile(dialect=dialect)).strip() + ';']
    statements.extend(str(CreateIndex(index).compile(dialect=dialect)).strip() + ';' for index in sorted(table.indexes, key=lambda index: index.name))
    return '\n'.join(line.rstrip() for line in '\n\n'.join(statements).splitlines()) + '\n'


if __name__ == '__main__':
    path = Path(__file__).resolve().parents[2] / 'database/schema/002_inference_decision.sql'
    if path.exists() and path.read_text(encoding='utf8') != render():
        raise ValueError('Migration already exists with different contents')
    path.write_text(render(), encoding='utf8', newline='\n')
    print(path.name)
