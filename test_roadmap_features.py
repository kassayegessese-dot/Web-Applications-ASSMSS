import base64
import hashlib
import hmac
import time
import unittest
from datetime import date

from app import create_app, create_email_action_token, get_mfa_cipher
from extensions import db, limiter
from init_db import migrate_school_classes
from models import (
    Attendance,
    EmailActionToken,
    Exam,
    Fee,
    SchoolClass,
    SchoolNews,
    Student,
    Subject,
    Teacher,
    User,
)


def make_totp(secret, timestamp=None):
    normalized = secret + '=' * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(normalized)
    counter = int((time.time() if timestamp is None else timestamp) // 30)
    digest = hmac.new(key, counter.to_bytes(8, 'big'), hashlib.sha1).digest()
    offset = digest[-1] & 0x0f
    value = int.from_bytes(digest[offset:offset + 4], 'big') & 0x7fffffff
    return f'{value % 1_000_000:06d}'


class RoadmapFeatureTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
            'SQLALCHEMY_DATABASE_URI': 'sqlite://',
            'SMTP_HOST': None,
            'SMTP_FROM_ADDRESS': None,
        })
        limiter.reset()
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def create_user(self, username, role, **values):
        with self.app.app_context():
            user = User(username=username, role=role, **values)
            user.set_password('ValidPassword!2026')
            db.session.add(user)
            db.session.commit()
            return user.id

    def login(self, username, role):
        with self.app.app_context():
            if not User.query.filter_by(username=username).first():
                user = User(username=username, role=role)
                user.set_password('ValidPassword!2026')
                db.session.add(user)
                db.session.commit()
        client = self.app.test_client()
        response = client.post('/auth/login', data={
            'username': username,
            'password': 'ValidPassword!2026',
            'role': role,
        })
        self.assertEqual(response.status_code, 302)
        return client

    def test_admin_class_crud_migrates_students_and_protects_occupied_classes(self):
        client = self.login('classadmin', 'Admin')
        created = client.post('/api/classes', json={'grade': '9', 'section': 'a'})
        self.assertEqual(created.status_code, 200)
        school_class = created.get_json()['class']
        self.assertEqual(school_class['section'], 'A')

        student = client.post('/api/students', json={
            'first_name': 'Mekdes',
            'last_name': 'Alemu',
            'grade': '9',
            'section': 'A',
        })
        self.assertEqual(student.status_code, 200)
        student_id = student.get_json()['student_id']
        self.assertEqual(student.get_json()['student']['class_id'], school_class['id'])

        updated = client.put(f"/api/classes/{school_class['id']}", json={
            'grade': '12',
            'section': 'B',
        })
        self.assertEqual(updated.status_code, 200)
        student_record = client.get(f'/api/students/{student_id}').get_json()
        self.assertEqual((student_record['grade'], student_record['section']), ('12', 'B'))
        blocked_delete = client.delete(f"/api/classes/{school_class['id']}")
        self.assertEqual(blocked_delete.status_code, 409)

        other_role = self.login('classstudent', 'Student')
        self.assertEqual(other_role.get('/api/classes').status_code, 403)

    def test_existing_grade_section_values_migrate_without_changing_student_records(self):
        with self.app.app_context():
            first = Student(first_name='Existing', last_name='Student', grade='10', section='B')
            second = Student(first_name='Another', last_name='Student', grade='10', section='B')
            unassigned = Student(first_name='Unassigned', last_name='Student', grade='11')
            db.session.add_all([first, second, unassigned])
            db.session.commit()
            migrate_school_classes()
            db.session.commit()
            self.assertEqual(first.class_id, second.class_id)
            self.assertEqual((first.grade, first.section), ('10', 'B'))
            self.assertIsNone(unassigned.class_id)
            migrate_school_classes()
            db.session.commit()
            self.assertEqual(SchoolClass.query.count(), 1)

    def test_parent_can_only_view_admin_linked_students_and_not_fees(self):
        admin = self.login('linkadmin', 'Admin')
        with self.app.app_context():
            parent = User(username='family', role='Parent', full_name='Family User')
            parent.set_password('ValidPassword!2026')
            child = Student(first_name='Saba', last_name='ParentLinked', grade='9', section='A')
            unrelated = Student(first_name='Private', last_name='Student', grade='10')
            teacher = Teacher(name='Parent visibility fixture')
            db.session.add_all([parent, child, unrelated, teacher])
            db.session.flush()
            child_id = child.student_id
            subject = Subject(subject_name='Mathematics', teacher_id=teacher.teacher_id)
            db.session.add(subject)
            db.session.flush()
            db.session.add_all([
                Attendance(student_id=child_id, date=date(2026, 10, 1), semester='one', status='present'),
                Exam(
                    student_id=child_id,
                    subject_id=subject.subject_id,
                    score=88,
                    max_score=100,
                    term='one',
                    exam_date=date(2026, 10, 1),
                ),
                Fee(student_id=child_id, amount=9876, status='unpaid'),
            ])
            db.session.commit()
            parent_id = parent.id

        response = admin.post('/api/parent-links', json={
            'parent_user_id': parent_id,
            'student_id': child_id,
        })
        self.assertEqual(response.status_code, 200)
        parent_client = self.login('family', 'Parent')
        dashboard = parent_client.get('/dashboard')
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b'Saba ParentLinked', dashboard.data)
        self.assertIn(b'Mathematics', dashboard.data)
        self.assertIn(b'88.0 / 100.0', dashboard.data)
        self.assertNotIn(b'Private Student', dashboard.data)
        self.assertNotIn(b'9876', dashboard.data)
        self.assertEqual(parent_client.get('/api/students').status_code, 403)

        unlink = admin.delete(f'/api/parent-links/{parent_id}/{child_id}')
        self.assertEqual(unlink.status_code, 200)
        self.assertNotIn(b'Private Student', dashboard.data)

    def test_news_drafts_are_private_until_published(self):
        admin = self.login('newsadmin', 'Admin')
        created = admin.post('/api/news', json={
            'title': 'School notice',
            'body': 'The science fair is next week. <script>alert(1)</script>',
        })
        self.assertEqual(created.status_code, 200)
        item = created.get_json()['news']
        public_page = self.app.test_client().get('/news')
        self.assertNotIn(b'School notice', public_page.data)

        published = admin.put(f"/api/news/{item['id']}", json={'status': 'published'})
        self.assertEqual(published.status_code, 200)
        public_page = self.app.test_client().get('/news')
        self.assertIn(b'School notice', public_page.data)
        self.assertIn(b'The science fair is next week. &lt;script&gt;alert(1)&lt;/script&gt;', public_page.data)
        self.assertNotIn(b'<script>alert(1)</script>', public_page.data)

        admin.put(f"/api/news/{item['id']}", json={'status': 'draft'})
        self.assertNotIn(b'School notice', self.app.test_client().get('/news').data)
        with self.app.app_context():
            self.assertEqual(SchoolNews.query.count(), 1)

    def test_admin_batch_configuration_updates_all_form_options(self):
        admin = self.login('batchadmin', 'Admin')
        result = admin.put('/api/settings/batches', json={
            'batches': ['2031', '2032'],
        })
        self.assertEqual(result.status_code, 200)
        self.assertEqual(admin.get('/api/settings/batches').get_json()['batches'], ['2031', '2032'])
        registration = self.app.test_client().get('/auth/register')
        self.assertIn(b'value="2031"', registration.data)
        self.assertNotIn(b'value="2024"', registration.data)

        duplicate = admin.put('/api/settings/batches', json={
            'batches': ['2031', '2031'],
        })
        self.assertEqual(duplicate.status_code, 400)

    def test_student_signup_remains_pending_until_admin_approval(self):
        with self.app.app_context():
            student = Student(
                first_name='Selam',
                last_name='Tadesse',
                dob=date(2010, 5, 4),
            )
            db.session.add(student)
            db.session.commit()
            student_id = student.student_id

        public_client = self.app.test_client()
        response = public_client.post('/auth/register', data={
            'role': 'Student',
            'student_id': str(student_id),
            'date_of_birth': '2010-05-04',
            'batch': '2026',
            'password': 'ValidPassword!2026',
            'confirm_password': 'ValidPassword!2026',
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = User.query.filter_by(student_id=student_id).one()
            self.assertEqual(user.approval_status, 'pending')
            self.assertFalse(user.is_active)
            user_id = user.id
            username = user.username

        admin = self.login('approvaladmin', 'Admin')
        self.assertEqual(admin.post(f'/api/users/{user_id}/toggle').status_code, 200)
        approved_login = self.app.test_client().post('/auth/login', data={
            'username': username,
            'password': 'ValidPassword!2026',
            'role': 'Student',
        })
        self.assertEqual(approved_login.status_code, 302)

    def test_email_reset_token_is_one_time_and_invalidates_old_sessions(self):
        user_id = self.create_user(
            'recoveryuser',
            'Parent',
            email='recovery@example.test',
            email_verified=True,
        )
        client = self.login('recoveryuser', 'Parent')
        with self.app.app_context():
            user = db.session.get(User, user_id)
            token = create_email_action_token(user, 'password_reset')

        reset_url = f'/auth/password-reset/{token}'
        self.assertEqual(client.get(reset_url).status_code, 200)
        reset = client.post(reset_url, data={
            'password': 'NewValidPassword!2026',
            'confirm_password': 'NewValidPassword!2026',
        })
        self.assertEqual(reset.status_code, 302)
        self.assertEqual(client.get('/dashboard').status_code, 302)
        self.assertEqual(self.app.test_client().get(reset_url).status_code, 400)

        new_login = self.app.test_client().post('/auth/login', data={
            'username': 'recoveryuser',
            'password': 'NewValidPassword!2026',
            'role': 'Parent',
        })
        self.assertEqual(new_login.status_code, 302)
        with self.app.app_context():
            self.assertEqual(EmailActionToken.query.filter_by(purpose='password_reset').count(), 1)

    def test_authenticator_enrollment_and_login_challenge(self):
        self.create_user('mfauser', 'Student')
        client = self.login('mfauser', 'Student')
        page = client.get('/auth/mfa/setup')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'name="password"', page.data)
        self.assertEqual(client.post('/auth/mfa/setup', data={
            'password': 'ValidPassword!2026',
        }).status_code, 302)
        self.assertEqual(client.get('/auth/mfa/setup').status_code, 200)
        with client.session_transaction() as session:
            self.assertNotIn('pending_mfa_secret', session)
            encrypted_secret = session['pending_mfa_secret_encrypted']
        with self.app.app_context():
            secret = get_mfa_cipher(self.app).decrypt(
                encrypted_secret.encode('ascii')
            ).decode('ascii')
        enabled = client.post('/auth/mfa/setup', data={
            'code': make_totp(secret),
        })
        self.assertEqual(enabled.status_code, 302)
        with self.app.app_context():
            user = User.query.filter_by(username='mfauser').one()
            self.assertTrue(user.mfa_enabled)
            self.assertNotIn(secret, user.mfa_secret_encrypted)

        client.post('/auth/logout')
        first_factor = client.post('/auth/login', data={
            'username': 'mfauser',
            'password': 'ValidPassword!2026',
            'role': 'Student',
        })
        self.assertEqual(first_factor.status_code, 302)
        self.assertEqual(first_factor.headers['Location'], '/auth/mfa')
        challenge = client.post('/auth/mfa', data={'code': make_totp(secret)})
        self.assertEqual(challenge.status_code, 302)
        self.assertEqual(challenge.headers['Location'], '/dashboard')

    def test_mfa_setup_key_can_be_rotated_after_exposure(self):
        client = self.login('mfarestartuser', 'Student')
        self.assertEqual(client.post('/auth/mfa/setup', data={
            'password': 'ValidPassword!2026',
        }).status_code, 302)
        client.get('/auth/mfa/setup')
        with client.session_transaction() as session:
            old_encrypted_secret = session['pending_mfa_secret_encrypted']
            old_secret = get_mfa_cipher(self.app).decrypt(
                old_encrypted_secret.encode('ascii')
            ).decode('ascii')

        rejected = client.post('/auth/mfa/setup/restart', data={
            'password': 'IncorrectPassword!2026',
        })
        self.assertEqual(rejected.status_code, 302)
        with client.session_transaction() as session:
            self.assertEqual(
                session['pending_mfa_secret_encrypted'],
                old_encrypted_secret,
            )

        restarted = client.post('/auth/mfa/setup/restart', data={
            'password': 'ValidPassword!2026',
        })
        self.assertEqual(restarted.status_code, 302)
        page = client.get('/auth/mfa/setup')
        self.assertEqual(page.status_code, 200)
        with client.session_transaction() as session:
            new_encrypted_secret = session['pending_mfa_secret_encrypted']
            new_secret = get_mfa_cipher(self.app).decrypt(
                new_encrypted_secret.encode('ascii')
            ).decode('ascii')
            self.assertNotIn('pending_mfa_secret', session)
        self.assertNotEqual(old_secret, new_secret)
        self.assertNotIn(old_secret.encode('ascii'), page.data)
        self.assertIn(new_secret.encode('ascii'), page.data)

    def test_email_verification_is_required_before_recovery(self):
        user_id = self.create_user(
            'unverifiedemail',
            'Parent',
            email='unverified@example.test',
            email_verified=False,
        )
        with self.app.app_context():
            token = create_email_action_token(
                db.session.get(User, user_id),
                'verify_email',
            )
        response = self.app.test_client().get(f'/auth/verify-email/{token}')
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertTrue(db.session.get(User, user_id).email_verified)

        reset_form = self.app.test_client().get('/auth/password-reset')
        self.assertEqual(reset_form.status_code, 200)
        request_response = self.app.test_client().post('/auth/password-reset', data={
            'email': 'unverified@example.test',
        }, follow_redirects=True)
        self.assertEqual(request_response.status_code, 200)
        self.assertIn(b'Email delivery must be configured', request_response.data)


if __name__ == '__main__':
    unittest.main()
