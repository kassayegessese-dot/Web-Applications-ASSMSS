import unittest

from sqlalchemy import create_engine, inspect, text

from config import normalize_database_url
from init_db import ensure_student_link_unique_index


class DatabaseConfigurationTests(unittest.TestCase):
    def test_mysql_urls_use_installed_pymysql_driver(self):
        normalized_url = normalize_database_url(
            'mysql://app:password@localhost/assms'
        )
        self.assertEqual(
            normalized_url,
            'mysql+pymysql://app:password@localhost/assms',
        )
        self.assertEqual(
            normalize_database_url('sqlite:///assms.db'),
            'sqlite:///assms.db',
        )
        engine = create_engine(normalized_url)
        try:
            self.assertEqual(engine.dialect.name, 'mysql')
            self.assertEqual(engine.dialect.driver, 'pymysql')
        finally:
            engine.dispose()

    def test_student_link_index_migration_is_portable_and_idempotent(self):
        engine = create_engine('sqlite://')
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    'CREATE TABLE users (id INTEGER PRIMARY KEY, student_id INTEGER)'
                ))

            ensure_student_link_unique_index(engine)
            ensure_student_link_unique_index(engine)

            indexes = inspect(engine).get_indexes('users')
            self.assertTrue(any(
                index['name'] == 'ix_users_student_id'
                and index['unique']
                and index['column_names'] == ['student_id']
                for index in indexes
            ))
        finally:
            engine.dispose()

    def test_student_link_index_migration_respects_existing_unique_constraint(self):
        engine = create_engine('sqlite://')
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    'CREATE TABLE users ('
                    'id INTEGER PRIMARY KEY, student_id INTEGER UNIQUE)'
                ))

            ensure_student_link_unique_index(engine)

            self.assertFalse(inspect(engine).get_indexes('users'))
            self.assertTrue(inspect(engine).get_unique_constraints('users'))
        finally:
            engine.dispose()


if __name__ == '__main__':
    unittest.main()
