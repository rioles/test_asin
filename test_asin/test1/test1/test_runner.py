"""
Lanceur de tests sans droit CREATEDB.

Par défaut, Django crée puis détruit une base « test_<nom> », ce qui exige le droit
CREATEDB. Si la variable DJANGO_TEST_SCHEMA est définie (ex. test_django), ce
lanceur utilise à la place un SCHÉMA jetable de la base existante :
  * il crée le schéma, y applique les migrations, lance les tests, puis le supprime ;
  * la connexion n'en voit pas d'autre (search_path, réglé dans settings.py), donc
    le schéma public et ses données ne sont jamais touchés ;
  * il ne crée ni ne supprime JAMAIS de base de données.

    $env:DJANGO_TEST_SCHEMA = "test_django"      # PowerShell
    ..\\venv\\Scripts\\python.exe manage.py test test1.tests

Sans la variable, comportement standard de Django.
"""
import os
import re

from django.core.management import call_command
from django.db import connections
from django.test.runner import DiscoverRunner


def _schema():
    schema = os.getenv("DJANGO_TEST_SCHEMA")
    if schema and not re.fullmatch(r"test_[a-z0-9_]{1,50}", schema):
        raise ValueError("DJANGO_TEST_SCHEMA doit commencer par « test_ » (minuscules, chiffres, _).")
    return schema


class SchemaTestRunner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        schema = _schema()
        if not schema:
            return super().setup_databases(**kwargs)
        conn = connections["default"]
        with conn.cursor() as c:
            c.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            c.execute(f'CREATE SCHEMA "{schema}"')
        conn.close()
        call_command("migrate", verbosity=0, interactive=False)
        return None

    def teardown_databases(self, old_config, **kwargs):
        schema = _schema()
        if not schema:
            return super().teardown_databases(old_config, **kwargs)
        connections.close_all()
        with connections["default"].cursor() as c:
            c.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        connections.close_all()
