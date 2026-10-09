import unittest

from app import create_app
from extensions import db
from models import Attendance, Book, Borrow, Exam, Fee, Student, Subject, Teacher
from seed_demo import seed_demo_data


class DemoSeedTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite://',
        })
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.drop_all()

    def test_seed_adds_related_fictional_data_once(self):
        seeded = seed_demo_data(self.app)
        self.assertEqual(seeded, {
            'students': 5,
            'teachers': 2,
            'subjects': 3,
            'attendance': 15,
            'exams': 15,
            'fees': 5,
            'books': 3,
            'borrows': 1,
        })

        with self.app.app_context():
            self.assertEqual(Student.query.count(), 5)
            self.assertEqual(
                {
                    grade: Student.query.filter_by(grade=grade).count()
                    for grade in ('9', '10', '11', '12')
                },
                {'9': 1, '10': 2, '11': 1, '12': 1},
            )
            self.assertEqual(Teacher.query.count(), 2)
            self.assertEqual(Subject.query.count(), 3)
            self.assertEqual(Attendance.query.count(), 15)
            self.assertEqual(Exam.query.count(), 15)
            self.assertEqual(Fee.query.count(), 5)
            self.assertEqual(Book.query.count(), 3)
            self.assertEqual(Borrow.query.count(), 1)
            self.assertEqual(Book.query.filter_by(isbn='DEMO-0001').one().available, 3)

        self.assertEqual(seed_demo_data(self.app), {
            'students': 0,
            'teachers': 0,
            'subjects': 0,
            'attendance': 0,
            'exams': 0,
            'fees': 0,
            'books': 0,
            'borrows': 0,
        })

    def test_seed_refuses_non_development_or_non_local_bind(self):
        self.app.config['ENVIRONMENT'] = 'production'
        with self.assertRaisesRegex(RuntimeError, 'only be added in development'):
            seed_demo_data(self.app)

        self.app.config.update(ENVIRONMENT='development', HOST='0.0.0.0')
        with self.assertRaisesRegex(RuntimeError, 'localhost-only'):
            seed_demo_data(self.app)


if __name__ == '__main__':
    unittest.main()
