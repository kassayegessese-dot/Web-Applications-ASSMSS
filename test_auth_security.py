import unittest
from datetime import date

from app import create_app, password_errors
from extensions import db, limiter
from init_db import create_demo_account
from models import (
    Attendance, AuditLog, Book, Borrow, Exam, Fee, Student, Subject, Teacher, User,
)


class AuthenticationSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
            'SQLALCHEMY_DATABASE_URI': 'sqlite://',
        })
        with cls.app.app_context():
            db.create_all()

    def setUp(self):
        self.app.config['WTF_CSRF_ENABLED'] = False
        limiter.reset()
        with self.app.app_context():
            db.drop_all()
            db.create_all()

    def _create_user(self, username, role):
        with self.app.app_context():
            user = User(username=username, role=role)
            user.set_password('ValidPassword!2026')
            db.session.add(user)
            db.session.commit()

    def _login(self, username, role):
        self._create_user(username, role)
        client = self.app.test_client()
        response = client.post('/auth/login', data={
            'username': username,
            'password': 'ValidPassword!2026',
            'role': role,
        })
        self.assertEqual(response.status_code, 302)
        return client

    def test_login_form_uses_username_without_email_field(self):
        response = self.app.test_client().get('/auth/login')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('name="username"', html)
        self.assertIn('ID / Username', html)
        for role in ('Admin', 'Teacher', 'Student', 'Parent'):
            self.assertIn(f'value="{role}"', html)
        self.assertNotIn('name="email"', html)

    def test_app_and_school_names_are_configurable_on_auth_pages(self):
        self.app.config.update(
            APP_NAME='Configured ASSMS',
            SCHOOL_NAME='Example Secondary School',
        )
        try:
            for path in ('/auth/login', '/auth/register'):
                with self.subTest(path=path):
                    response = self.app.test_client().get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(b'Configured ASSMS', response.data)
                    self.assertIn(b'Example Secondary School', response.data)
        finally:
            self.app.config.update(APP_NAME='ASSMS', SCHOOL_NAME='Aylota Secondary School')

    def test_public_site_pages_are_available_without_authentication(self):
        client = self.app.test_client()
        pages = {
            '/': (b'School information and services', b'Sign in to ASSMS'),
            '/about': (b'Our school', b'Aylota Secondary School'),
            '/admissions': (b'Joining the portal', b'Student ID and'),
            '/academics': (b'Learning records', b'Attendance'),
            '/news': (b'School updates', b'No public announcements are available'),
            '/contact': (b'Application support', b'kassayegessese@gmail.com'),
        }
        for path, expected_content in pages.items():
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                for content in expected_content:
                    self.assertIn(content, response.data)

    def test_public_navigation_contains_all_requested_pages_and_login(self):
        response = self.app.test_client().get('/')
        self.assertEqual(response.status_code, 200)
        for path in (
            '/about', '/admissions', '/academics', '/news', '/contact', '/auth/login',
        ):
            with self.subTest(path=path):
                self.assertIn(path.encode(), response.data)
        self.assertIn(b'name="viewport"', response.data)

    def test_design_system_font_and_palette_are_shared_across_public_and_portal(self):
        client = self.app.test_client()
        for path in ('/', '/auth/login', '/auth/register'):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'fonts.googleapis.com/css2?family=Inter', response.data)

        stylesheet = client.get('/static/css/style.css')
        self.assertEqual(stylesheet.status_code, 200)
        try:
            css = stylesheet.data.lower()
            for design_token in (
                b'--primary: #2563eb',
                b'--secondary: #1e293b',
                b'--success: #16a34a',
                b'--warning: #f59e0b',
                b'--danger: #dc2626',
                b'--bg-light: #f8fafc',
                b'.modal-content',
                b'.attendance-chart',
            ):
                with self.subTest(token=design_token):
                    self.assertIn(design_token, css)
        finally:
            stylesheet.close()

    def test_root_sends_authenticated_users_to_their_dashboard(self):
        client = self._login('rootadmin', 'Admin')
        response = client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], '/dashboard')

    def test_demo_credentials_are_disclosed_only_in_development_login(self):
        original_environment = self.app.config['ENVIRONMENT']
        try:
            self.app.config['ENVIRONMENT'] = 'development'
            development_page = self.app.test_client().get('/auth/login')
            self.assertNotIn(b'admin123', development_page.data)
            self.assertNotIn(b'For the demo', development_page.data)
            self.assertNotIn(b'Goodbye, admin', development_page.data)

            self.app.config['ENVIRONMENT'] = 'production'
            production_page = self.app.test_client().get('/auth/login')
            self.assertNotIn(b'admin123', production_page.data)
            self.assertNotIn(b'Goodbye, admin', production_page.data)
        finally:
            self.app.config['ENVIRONMENT'] = original_environment

    def test_logout_redirects_without_a_goodbye_message(self):
        client = self._login('adminuser', 'Admin')
        login_page = client.get('/auth/login')
        self.assertNotIn(b'Goodbye, adminuser', login_page.data)

        logout_response = client.post('/auth/logout', follow_redirects=True)
        self.assertEqual(logout_response.status_code, 200)
        self.assertNotIn(b'Goodbye, adminuser', logout_response.data)
    def test_registration_form_supports_email_parent_and_batch(self):
        response = self.app.test_client().get('/auth/register')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('name="email"', html)
        self.assertIn('value="Parent"', html)
        self.assertIn('value="Student"', html)
        self.assertIn('value="Teacher"', html)
        self.assertIn('value="Admin"', html)
        self.assertIn('name="batch"', html)
        self.assertIn('value="2030"', html)
        self.assertIn('name="date_of_birth"', html)

    def test_auth_and_app_templates_use_school_logo(self):
        client = self.app.test_client()
        for path in ('/auth/login', '/auth/register'):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'/static/images/aylota-logo.png', response.data)

    def test_settings_page_requires_login_and_shows_developer_contact(self):
        client = self.app.test_client()
        response = client.get('/settings')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/auth/login', response.headers['Location'])

        response = self._login('settingsadmin', 'Admin').get('/settings')
        self.assertEqual(response.status_code, 200)
        for detail in (
            'Kassaye Gessese Kahante',
            '0993408171',
            'kassayegessese@gmail.com',
            'South Ethiopia, Konso Ethiopia',
            'Web Application Developer',
            'darkThemePreference',
            'Acknowledgement',
            'school leadership and staff',
            'students and families',
            'Your account',
            'Workspace preferences',
            'Project overview',
            'Flask web application',
            'Python 3.12',
            'HTML5',
            'CSS3',
            'JavaScript',
            'Bootstrap 5.3',
            'Font Awesome 6.5',
            'Waitress WSGI server',
            'Application modules',
            'Roles &amp; permissions',
            'Administrator',
            'Teacher',
            'Student',
            'Parent',
            'Capabilities and remaining setup',
            'Parent-to-student links',
            'News publishing',
            'Student sign-up verification',
            'Recovery &amp; multi-factor sign-in',
            'authenticator-app MFA',
        ):
            with self.subTest(detail=detail):
                self.assertIn(detail.encode(), response.data)

    def test_password_policy_requires_eight_mixed_characters(self):
        self.assertTrue(password_errors('weak'))
        self.assertEqual(password_errors('Aa1!bcde'), [])
        self.assertTrue(password_errors('Aa1!bcd'))
        self.assertEqual(password_errors('ValidPassword!2026'), [])

    def test_login_requires_the_selected_account_type_to_match(self):
        self._create_user('teacher-id', 'Teacher')
        response = self.app.test_client().post('/auth/login', data={
            'username': 'teacher-id',
            'password': 'ValidPassword!2026',
            'role': 'Admin',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Invalid username or password', response.data)

    def test_public_admin_registration_waits_for_approval(self):
        client = self.app.test_client()
        response = client.post('/auth/register', data={
            'role': 'Admin',
            'batch': '2026',
            'password': 'ValidPassword!2026',
            'confirm_password': 'ValidPassword!2026',
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = User.query.one()
            self.assertEqual(user.role, 'Admin')
            self.assertFalse(user.is_active)
            self.assertEqual(user.approval_status, 'pending')
            username = user.username
        response = client.post('/auth/login', data={
            'role': 'Admin',
            'username': username,
            'password': 'ValidPassword!2026',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'awaiting administrator approval', response.data)

    def test_admin_can_approve_public_teacher_registration(self):
        public_client = self.app.test_client()
        response = public_client.post('/auth/register', data={
            'role': 'Teacher',
            'batch': '2026',
            'password': 'ValidPassword!2026',
            'confirm_password': 'ValidPassword!2026',
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            teacher = User.query.filter_by(role='Teacher').one()
            teacher_id = teacher.id
            teacher_username = teacher.username
            self.assertEqual(teacher.approval_status, 'pending')

        admin_client = self._login('adminuser', 'Admin')
        approval = admin_client.post(f'/api/users/{teacher_id}/toggle')
        self.assertEqual(approval.status_code, 200)
        self.assertTrue(approval.get_json()['active'])

        login = self.app.test_client().post('/auth/login', data={
            'username': teacher_username,
            'password': 'ValidPassword!2026',
            'role': 'Teacher',
        })
        self.assertEqual(login.status_code, 302)

    def test_parent_registration_gets_parent_id_and_batch(self):
        response = self.app.test_client().post('/auth/register', data={
            'role': 'Parent',
            'full_name': 'Test Parent',
            'batch': '2026',
            'password': 'ValidPassword!2026',
            'confirm_password': 'ValidPassword!2026',
            'email': 'ignored@example.test',
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = User.query.one()
            self.assertRegex(user.username, r'^PAR-\d{4,}$')
            self.assertEqual(user.role, 'Parent')
            self.assertEqual(user.batch, '2026')
            self.assertEqual(user.email, 'ignored@example.test')
            self.assertFalse(user.email_verified)

    def test_public_student_registration_verifies_student_id_and_birth_date(self):
        with self.app.app_context():
            student = Student(
                first_name='Ada',
                last_name='Lovelace',
                dob=date(2010, 12, 10),
            )
            db.session.add(student)
            db.session.commit()
            student_id = student.student_id

        response = self.app.test_client().post('/auth/register', data={
            'role': 'Student',
            'student_id': str(student_id),
            'date_of_birth': '2010-12-10',
            'batch': '2026',
            'password': 'ValidPassword!2026',
            'confirm_password': 'ValidPassword!2026',
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = User.query.one()
            self.assertEqual(user.role, 'Student')
            self.assertEqual(user.username, str(student_id))
            self.assertEqual(user.student_id, student_id)
            self.assertFalse(user.is_active)
            self.assertEqual(user.approval_status, 'pending')
            self.assertEqual(user.full_name, 'Ada Lovelace')

    def test_public_student_registration_rejects_wrong_birth_date(self):
        with self.app.app_context():
            student = Student(first_name='Ada', last_name='Lovelace', dob=date(2010, 12, 10))
            db.session.add(student)
            db.session.commit()
            student_id = student.student_id

        response = self.app.test_client().post('/auth/register', data={
            'role': 'Student',
            'student_id': str(student_id),
            'date_of_birth': '2010-12-11',
            'batch': '2026',
            'password': 'ValidPassword!2026',
            'confirm_password': 'ValidPassword!2026',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Student ID could not be verified', response.data)
        with self.app.app_context():
            self.assertEqual(User.query.count(), 0)

    def test_parent_has_safe_dashboard_without_school_data_access(self):
        client = self._login('parentuser', 'Parent')
        dashboard = client.get('/dashboard')
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b'No student records are linked to this Parent account yet.', dashboard.data)
        self.assertIn(b'Parent Portal', dashboard.data)
        self.assertIn(b'Parent Home', dashboard.data)
        self.assertEqual(client.get('/api/students').status_code, 403)
        self.assertEqual(client.get('/users').status_code, 302)

    def test_student_dashboard_shows_only_linked_student_records(self):
        with self.app.app_context():
            student = Student(first_name='Ada', last_name='Lovelace', grade='10')
            other_student = Student(first_name='Grace', last_name='Hopper', grade='11')
            teacher = Teacher(name='Test Teacher')
            db.session.add_all([student, other_student, teacher])
            db.session.flush()
            subject = Subject(subject_name='Mathematics', teacher_id=teacher.teacher_id)
            db.session.add(subject)
            db.session.flush()
            db.session.add_all([
                Attendance(
                    student_id=student.student_id, date=date(2026, 9, 1),
                    semester='one', status='present', remarks='Own attendance note',
                ),
                Attendance(
                    student_id=other_student.student_id, date=date(2026, 9, 2),
                    semester='one', status='absent', remarks='Other student private note',
                ),
                Exam(
                    student_id=student.student_id, subject_id=subject.subject_id,
                    score=95, term='one',
                ),
                Exam(
                    student_id=other_student.student_id, subject_id=subject.subject_id,
                    score=25, term='one',
                ),
            ])
            user = User(
                username=str(student.student_id),
                role='Student',
                full_name='Ada Lovelace',
                student_id=student.student_id,
            )
            user.set_password('ValidPassword!2026')
            db.session.add(user)
            db.session.commit()
            student_id = student.student_id

        client = self.app.test_client()
        login = client.post('/auth/login', data={
            'username': str(student_id),
            'password': 'ValidPassword!2026',
            'role': 'Student',
        })
        self.assertEqual(login.status_code, 302)
        response = client.get('/dashboard')
        self.assertEqual(response.status_code, 200)
        for own_detail in (
            b'My Attendance',
            b'My Exam Results',
            b'Own attendance note',
            b'Mathematics',
            b'95',
        ):
            self.assertIn(own_detail, response.data)
        for other_detail in (b'Grace Hopper', b'Other student private note', b'>25<'):
            self.assertNotIn(other_detail, response.data)

    def test_student_and_parent_navigation_excludes_staff_pages(self):
        for username, role, dashboard_label in (
            ('portalstudent', 'Student', 'My Records'),
            ('portalparent', 'Parent', 'Parent Home'),
        ):
            client = self._login(username, role)
            response = client.get('/dashboard')
            self.assertEqual(response.status_code, 200)
            self.assertIn(dashboard_label.encode(), response.data)
            for restricted_label in (
                b'>Students</span>',
                b'>Teachers</span>',
                b'>Attendance</span>',
                b'>Examinations</span>',
                b'>Finance</span>',
                b'>Users</span>',
                b'>Reports</span>',
            ):
                self.assertNotIn(restricted_label, response.data)
            self.assertEqual(client.get('/settings').status_code, 200)
            for path in (
                '/students', '/teachers', '/classes', '/attendance', '/exams',
                '/library', '/finance', '/users', '/reports',
            ):
                with self.subTest(role=role, path=path):
                    self.assertEqual(client.get(path).status_code, 302)

    def test_role_dashboards_omit_personal_welcome_and_developer_credit(self):
        for role, username in (
            ('Admin', 'dashboardadmin'),
            ('Teacher', 'dashboardteacher'),
            ('Student', 'dashboardstudent'),
            ('Parent', 'dashboardparent'),
        ):
            with self.subTest(role=role):
                response = self._login(username, role).get('/dashboard')
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(b'Welcome', response.data)
                self.assertNotIn(b'Academic overview', response.data)
                self.assertNotIn(b'Kassaye Gessese Kahante', response.data)

    def test_teacher_and_admin_have_distinct_management_permissions(self):
        teacher_client = self._login('teacherpermissions', 'Teacher')
        admin_client = self._login('adminpermissions', 'Admin')
        teacher_dashboard = teacher_client.get('/dashboard')
        self.assertEqual(teacher_dashboard.status_code, 200)
        self.assertIn(b'Teacher Dashboard', teacher_dashboard.data)
        self.assertNotIn(b'Recent Activities', teacher_dashboard.data)
        self.assertNotIn(b'pending account approvals', teacher_dashboard.data)
        for module_label in (
            b'>Students</span>', b'>Teachers</span>', b'>Classes</span>',
            b'>Examinations</span>', b'>Library</span>',
            b'>Finance</span>', b'>Reports</span>', b'>Users</span>',
        ):
            self.assertNotIn(module_label, teacher_dashboard.data)
        self.assertIn(b'>Attendance</span>', teacher_dashboard.data)
        for path in (
            '/students', '/teachers', '/classes', '/exams',
            '/library', '/reports', '/finance', '/users',
        ):
            with self.subTest(role='Teacher', path=path):
                self.assertEqual(teacher_client.get(path).status_code, 302)
        self.assertEqual(teacher_client.get('/attendance').status_code, 200)
        for path in (
            '/students', '/teachers', '/classes', '/attendance', '/exams',
            '/library', '/finance', '/users', '/reports',
        ):
            with self.subTest(role='Admin', path=path):
                self.assertEqual(admin_client.get(path).status_code, 200)
        admin_dashboard = admin_client.get('/dashboard')
        self.assertEqual(admin_dashboard.status_code, 200)
        for module_label in (
            b'>Students</span>', b'>Teachers</span>', b'>Classes</span>',
            b'>Attendance</span>', b'>Examinations</span>', b'>Library</span>',
            b'>Finance</span>', b'>Reports</span>', b'>Users</span>',
        ):
            self.assertIn(module_label, admin_dashboard.data)

    def test_teacher_cannot_access_admin_user_management(self):
        client = self._login('teacherusers', 'Teacher')
        self.assertEqual(client.get('/users').status_code, 302)
        response = client.get('/api/users')
        self.assertEqual(response.status_code, 403)

    def test_admin_dashboard_uses_live_metrics_and_shows_recent_activity(self):
        client = self._login('dashboardadmin', 'Admin')
        with self.app.app_context():
            admin = User.query.filter_by(username='dashboardadmin').one()
            student = Student(first_name='Recent', last_name='Student', grade='10')
            teacher = Teacher(name='Recent Teacher')
            pending_user = User(
                username='TCH-PENDING',
                role='Teacher',
                is_active_flag=False,
                approval_status='pending',
            )
            pending_user.set_password('ValidPassword!2026')
            db.session.add_all([student, teacher, pending_user])
            db.session.flush()
            recent_student_user = User(
                username='STU-RECENT',
                role='Student',
                full_name='Recent Student',
                student_id=student.student_id,
            )
            recent_student_user.set_password('ValidPassword!2026')
            recent_teacher_user = User(
                username='TCH-RECENT',
                role='Teacher',
                full_name='Recent Teacher',
            )
            recent_teacher_user.set_password('ValidPassword!2026')
            db.session.add_all([recent_student_user, recent_teacher_user])
            db.session.add_all([
                Subject(
                    subject_name='Dashboard Mathematics',
                    subject_code='DASH-MATH',
                    teacher_id=teacher.teacher_id,
                ),
                Attendance(
                    student_id=student.student_id,
                    date=date.today(),
                    semester='one',
                    status='present',
                ),
                AuditLog(
                    user_id=admin.id,
                    action='CREATE_STUDENT',
                    details=f'Student ID: {student.student_id}',
                ),
            ])
            db.session.commit()

        page = client.get('/dashboard')
        self.assertEqual(page.status_code, 200)
        for expected in (
            b'Dashboard',
            b'Subjects \xc2\xb7 Classes module',
            b'Attendance',
            b'Daily records \xc2\xb7 last 7 days',
            b'Recent Users',
            b'Recent Activities',
            b'Recent Student',
            b'Recent Teacher',
            b'TCH-PENDING',
            b'CREATE_STUDENT',
            b'pending account approvals',
            b'1 present, 0 absent, 0 late',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, page.data)
        self.assertIn(b'aria-label="1 pending account approvals"', page.data)
        self.assertNotIn(b'>850<', page.data)
        self.assertNotIn(b'>42<', page.data)
        self.assertNotIn(b'>24<', page.data)

    def test_teacher_dashboard_only_role_cannot_access_management_apis(self):
        client = self._login('teacherapiaccess', 'Teacher')
        for path in (
            '/api/students',
            '/api/teachers',
            '/api/subjects',
            '/api/exams',
            '/api/books',
            '/api/borrows',
            '/api/reports/students',
        ):
            with self.subTest(method='GET', path=path):
                self.assertEqual(client.get(path).status_code, 403)
        for path, payload, expected_status in (
            ('/api/students', {'first_name': 'No', 'last_name': 'Access'}, 403),
            ('/api/exams', {}, 403),
            ('/api/books', {}, 403),
            ('/alarms/schedule', {}, 302),
        ):
            with self.subTest(method='POST', path=path):
                self.assertEqual(
                    client.post(path, json=payload).status_code,
                    expected_status,
                )
        self.assertEqual(client.get('/api/attendance').status_code, 200)
        self.assertEqual(client.get('/api/attendance/students').status_code, 200)
        self.assertEqual(
            client.post('/api/attendance', json={}).status_code,
            400,
        )

    def test_teacher_can_record_attendance_but_cannot_access_student_management(self):
        with self.app.app_context():
            student = Student(first_name='Teacher', last_name='Roster')
            db.session.add(student)
            db.session.commit()
            student_id = student.student_id

        teacher = self._login('attendanceteacher', 'Teacher')
        self.assertEqual(teacher.get('/api/students').status_code, 403)
        roster = teacher.get('/api/attendance/students')
        self.assertEqual(roster.status_code, 200)
        self.assertEqual(roster.get_json(), [{
            'student_id': student_id,
            'full_name': 'Teacher Roster',
            'grade': None,
            'section': None,
        }])
        response = teacher.post('/api/attendance', json={
            'student_id': student_id,
            'date': '2026-10-08',
            'semester': 'one',
            'status': 'present',
        })
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            record = Attendance.query.one()
            self.assertEqual(record.student_id, student_id)
            self.assertEqual(record.status, 'present')
            self.assertEqual(
                AuditLog.query.filter_by(action='RECORD_ATTENDANCE').count(),
                1,
            )

    def test_teacher_records_include_assigned_subjects_and_not_fake_status(self):
        client = self._login('teachersubjectadmin', 'Admin')
        with self.app.app_context():
            teacher = Teacher(name='Subject Teacher', phone='555-0100')
            db.session.add(teacher)
            db.session.flush()
            db.session.add(Subject(
                subject_name='Biology',
                subject_code='BIO-TEACHER',
                teacher_id=teacher.teacher_id,
            ))
            db.session.commit()

        response = client.get('/api/teachers')
        self.assertEqual(response.status_code, 200)
        teacher_record = response.get_json()[0]
        self.assertEqual(teacher_record['subjects'], ['Biology'])
        page = client.get('/teachers')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Search by name, subject, phone', page.data)
        self.assertIn(b'Employment status is not currently tracked', page.data)
        self.assertIn(b'Edit Teacher', page.data)

    def test_class_groups_include_requested_grades_and_use_recorded_sections(self):
        client = self._login('classgroupadmin', 'Admin')
        response = client.get('/classes')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Grade and section groups', response.data)
        self.assertIn(b'/api/students', response.data)
        self.assertIn(b'data-default-grades=\'["9", "12"]\'', response.data)
        self.assertIn(b'Manage sections', response.data)
        self.assertIn(b'/api/classes', response.data)
        self.assertNotIn(b'Sections: A, B, C', response.data)

    def test_unauthenticated_api_requests_return_json_401(self):
        response = self.app.test_client().get('/api/users')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {'error': 'Authentication required'})

    def test_teacher_cannot_access_student_profiles_and_admin_can_see_fees(self):
        with self.app.app_context():
            student = Student(first_name='Ada', last_name='Lovelace')
            db.session.add(student)
            db.session.flush()
            db.session.add(Fee(student_id=student.student_id, amount=250, status='unpaid'))
            db.session.commit()
            student_id = student.student_id

        teacher_response = self._login('profileteacher', 'Teacher').get(
            f'/api/students/{student_id}/profile'
        )
        self.assertEqual(teacher_response.status_code, 403)

        admin_response = self._login('profileadmin', 'Admin').get(
            f'/api/students/{student_id}/profile'
        )
        self.assertEqual(admin_response.status_code, 200)
        self.assertEqual(admin_response.get_json()['fees']['total'], 250)

    def test_admin_user_table_headers_match_user_data_columns(self):
        response = self._login('userspageadmin', 'Admin').get('/users')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for heading in (
            'User #', 'Account ID', 'Full Name', 'Student ID', 'Batch',
            'Role', 'Status', 'Email', 'Actions',
        ):
            with self.subTest(heading=heading):
                self.assertIn(f'>{heading}</th>', html)
        self.assertIn('colspan="9"', html)

    def test_admin_user_management_actions_are_audited(self):
        client = self._login('auditadmin', 'Admin')
        response = client.post('/api/users', json={
            'role': 'Teacher',
            'batch': '2026',
            'password': 'ValidPassword!2026',
        })
        self.assertEqual(response.status_code, 200)
        user_id = response.get_json()['user']['id']
        with self.app.app_context():
            create_log = AuditLog.query.filter_by(action='CREATE_USER').one()
            self.assertNotIn('ValidPassword!2026', create_log.details)

        response = client.post(f'/api/users/{user_id}/toggle')
        self.assertEqual(response.status_code, 200)
        response = client.delete(f'/api/users/{user_id}')
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            actions = {
                log.action
                for log in AuditLog.query.filter(
                    AuditLog.action.in_(['CREATE_USER', 'UPDATE_USER_STATUS', 'DELETE_USER'])
                ).all()
            }
        self.assertEqual(actions, {'CREATE_USER', 'UPDATE_USER_STATUS', 'DELETE_USER'})

    def test_student_api_rejects_malformed_text_and_date_values(self):
        client = self._login('validationadmin', 'Admin')
        for payload in (
            {'first_name': 123, 'last_name': 'Lovelace'},
            {'first_name': 'Ada', 'last_name': 'Lovelace', 'dob': 123},
            {'first_name': ' ', 'last_name': 'Lovelace'},
        ):
            with self.subTest(payload=payload):
                response = client.post('/api/students', json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn('message', response.get_json())
        with self.app.app_context():
            self.assertEqual(Student.query.count(), 0)

    def test_duplicate_admin_managed_identifiers_return_conflicts(self):
        client = self._login('duplicateadmin', 'Admin')
        user_payload = {
            'role': 'Teacher',
            'batch': '2026',
            'email': 'teacher@example.test',
            'password': 'ValidPassword!2026',
        }
        self.assertEqual(client.post('/api/users', json=user_payload).status_code, 200)
        self.assertEqual(client.post('/api/users', json=user_payload).status_code, 409)

        book_payload = {'title': 'Reference Book', 'isbn': 'ISBN-100'}
        self.assertEqual(client.post('/api/books', json=book_payload).status_code, 200)
        self.assertEqual(client.post('/api/books', json=book_payload).status_code, 409)

        subject_payload = {'subject_name': 'Mathematics', 'subject_code': 'MATH-1'}
        self.assertEqual(client.post('/api/subjects', json=subject_payload).status_code, 200)
        self.assertEqual(client.post('/api/subjects', json=subject_payload).status_code, 409)

    def test_teacher_and_book_deletion_preserve_linked_records(self):
        client = self._login('recordsadmin', 'Admin')
        with self.app.app_context():
            teacher = Teacher(name='Ada Teacher')
            student = Student(first_name='Ada', last_name='Lovelace')
            book = Book(title='Reference Book', quantity=1, available=0)
            db.session.add_all([teacher, student, book])
            db.session.flush()
            subject = Subject(subject_name='Mathematics', teacher_id=teacher.teacher_id)
            db.session.add(subject)
            db.session.flush()
            db.session.add(Exam(student_id=student.student_id, subject_id=subject.subject_id, score=90))
            db.session.add(Borrow(book_id=book.book_id, student_id=student.student_id))
            db.session.commit()
            teacher_id = teacher.teacher_id
            subject_id = subject.subject_id
            book_id = book.book_id

        teacher_response = client.delete(f'/api/teachers/{teacher_id}')
        self.assertEqual(teacher_response.status_code, 409)
        subject_response = client.delete(f'/api/subjects/{subject_id}')
        self.assertEqual(subject_response.status_code, 409)
        book_response = client.delete(f'/api/books/{book_id}')
        self.assertEqual(book_response.status_code, 409)
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Teacher, teacher_id))
            self.assertIsNotNone(db.session.get(Subject, subject_id))
            self.assertIsNotNone(db.session.get(Book, book_id))
            self.assertEqual(Exam.query.count(), 1)
            self.assertEqual(Borrow.query.count(), 1)

    def test_student_deletion_preserves_school_history(self):
        client = self._login('studentrecordsadmin', 'Admin')
        with self.app.app_context():
            student = Student(first_name='Grace', last_name='Hopper')
            db.session.add(student)
            db.session.flush()
            db.session.add(Fee(student_id=student.student_id, amount=400, status='paid'))
            db.session.commit()
            student_id = student.student_id

        response = client.delete(f'/api/students/{student_id}')
        self.assertEqual(response.status_code, 409)
        self.assertIn('school records', response.get_json()['message'])
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Student, student_id))
            self.assertEqual(Fee.query.filter_by(student_id=student_id).count(), 1)

    def test_admin_can_create_privileged_roles_and_parent(self):
        client = self._login('adminuser', 'Admin')
        for role in ('Admin', 'Teacher', 'Parent'):
            with self.subTest(role=role):
                response = client.post('/api/users', json={
                    'full_name': f'Managed {role}',
                    'batch': '2026',
                    'role': role,
                    'password': 'ValidPassword!2026',
                })
                self.assertEqual(response.status_code, 200)
                result = response.get_json()
                prefixes = {'Admin': 'ADM', 'Teacher': 'TCH', 'Parent': 'PAR'}
                self.assertRegex(
                    result['user']['username'],
                    rf'^{prefixes[role]}-\d{{4,}}$',
                )
                self.assertEqual(result['user']['role'], role)
                self.assertEqual(result['user']['batch'], '2026')

    def test_admin_creates_student_account_with_unique_school_id_username(self):
        client = self._login('adminuser', 'Admin')
        users_page = client.get('/users')
        self.assertEqual(users_page.status_code, 200)
        self.assertIn(b'id="uStudentId"', users_page.data)

        with self.app.app_context():
            student = Student(first_name='Ada', last_name='Lovelace')
            db.session.add(student)
            db.session.commit()
            student_id = student.student_id

        payload = {
            'role': 'Student',
            'student_id': student_id,
            'batch': '2026',
            'password': 'ValidPassword!2026',
        }
        response = client.post('/api/users', json=payload)
        self.assertEqual(response.status_code, 200)
        result = response.get_json()['user']
        self.assertEqual(result['username'], str(student_id))
        self.assertEqual(result['student_id'], student_id)
        self.assertEqual(result['full_name'], 'Ada Lovelace')

        duplicate = client.post('/api/users', json=payload)
        self.assertEqual(duplicate.status_code, 409)

    def test_admin_cannot_create_student_account_without_existing_record(self):
        client = self._login('adminuser', 'Admin')
        response = client.post('/api/users', json={
            'role': 'Student',
            'student_id': 987654,
            'batch': '2026',
            'password': 'ValidPassword!2026',
        })
        self.assertEqual(response.status_code, 404)

    def test_student_cannot_read_school_wide_or_finance_data(self):
        client = self._login('studentuser', 'Student')
        self.assertEqual(client.get('/dashboard').status_code, 200)
        self.assertEqual(client.get('/api/students').status_code, 403)
        self.assertEqual(client.get('/api/fees').status_code, 403)
        self.assertEqual(client.get('/finance').status_code, 302)

    def test_admin_can_access_finance(self):
        client = self._login('adminuser', 'Admin')
        self.assertEqual(client.get('/finance').status_code, 200)
        self.assertEqual(client.get('/api/fees').status_code, 200)

    def test_student_form_offers_grade_nine_and_twelve(self):
        response = self._login('gradeadmin', 'Admin').get('/students')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<datalist id="gradeOptions">', response.data)
        self.assertIn(b'<option value="9" label="Grade 9">', response.data)
        self.assertIn(b'<option value="12" label="Grade 12">', response.data)

    def test_csrf_rejects_mutating_request_without_token(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        response = self.app.test_client().post('/api/users', json={'username': 'csrfuser'})
        self.assertEqual(response.status_code, 400)

    def test_invalid_numeric_filters_return_client_errors(self):
        client = self._login('filteradmin', 'Admin')
        paths = (
            '/api/attendance?student_id=not-an-int',
            '/api/exams?student_id=not-an-int',
            '/api/exams?subject_id=not-an-int',
            '/api/fees?student_id=not-an-int',
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 400)

    def test_fee_rejects_invalid_date_amount_and_status(self):
        client = self._login('feeadmin', 'Admin')
        with self.app.app_context():
            student = Student(first_name='Fee', last_name='Test')
            db.session.add(student)
            db.session.commit()
            student_id = student.student_id

        base_payload = {'student_id': student_id, 'amount': 25}
        invalid_date = client.post('/api/fees', json={
            **base_payload,
            'date': 'not-a-date',
        })
        negative_amount = client.post('/api/fees', json={
            **base_payload,
            'amount': -1,
        })
        invalid_status = client.post('/api/fees', json={
            **base_payload,
            'status': 'overdue-ish',
        })
        self.assertEqual(invalid_date.status_code, 400)
        self.assertEqual(negative_amount.status_code, 400)
        self.assertEqual(invalid_status.status_code, 400)

    def test_book_rejects_invalid_or_negative_quantity(self):
        client = self._login('bookadmin', 'Admin')
        for quantity in ('not-an-int', -2, 0):
            with self.subTest(quantity=quantity):
                response = client.post('/api/books', json={
                    'title': 'Validation test',
                    'quantity': quantity,
                })
                self.assertEqual(response.status_code, 400)

    def test_mutation_endpoints_reject_non_object_json_without_server_errors(self):
        client = self._login('payloadadmin', 'Admin')
        endpoints = (
            ('POST', '/api/students'),
            ('PUT', '/api/students/1'),
            ('POST', '/api/teachers'),
            ('PUT', '/api/teachers/1'),
            ('POST', '/api/subjects'),
            ('POST', '/api/attendance'),
            ('POST', '/api/exams'),
            ('POST', '/api/fees'),
            ('PUT', '/api/fees/1'),
            ('POST', '/api/books'),
            ('PUT', '/api/books/1'),
            ('POST', '/api/borrows'),
            ('POST', '/api/users'),
            ('POST', '/alarms/schedule'),
        )
        invalid_bodies = (
            {'json': ['not', 'an', 'object']},
            {},
            {'data': 'not JSON', 'content_type': 'text/plain'},
        )
        for method, path in endpoints:
            for body in invalid_bodies:
                with self.subTest(method=method, path=path, body=body):
                    response = client.open(path, method=method, **body)
                    self.assertEqual(response.status_code, 400)

    def test_attendance_exams_reports_and_dashboard_are_semester_specific(self):
        client = self._login('semesteradmin', 'Admin')
        with self.app.app_context():
            student = Student(first_name='Semester', last_name='Student')
            subject = Subject(subject_name='Mathematics', subject_code='MATH-SEM')
            db.session.add_all([student, subject])
            db.session.commit()
            student_id = student.student_id
            subject_id = subject.subject_id

        for index, semester in enumerate(('one', 'two', 'three'), start=1):
            attendance = client.post('/api/attendance', json={
                'student_id': student_id,
                'date': f'2026-0{index}-10',
                'status': 'present',
                'semester': semester,
            })
            exam = client.post('/api/exams', json={
                'student_id': student_id,
                'subject_id': subject_id,
                'score': index * 20,
                'semester': semester,
            })
            self.assertEqual(attendance.status_code, 200)
            self.assertEqual(exam.status_code, 200)

        for semester, expected_score in (('one', 20), ('two', 40), ('three', 60)):
            with self.subTest(semester=semester):
                attendance = client.get(f'/api/attendance?semester={semester}').get_json()
                exams = client.get(f'/api/exams?semester={semester}').get_json()
                report = client.get(f'/api/reports/exams?semester={semester}').get_json()
                students = client.get(f'/api/students?semester={semester}').get_json()
                self.assertEqual(len(attendance), 1)
                self.assertEqual(attendance[0]['semester'], semester)
                self.assertEqual(len(exams), 1)
                self.assertEqual(exams[0]['semester'], semester)
                self.assertEqual(exams[0]['score'], expected_score)
                self.assertEqual(report[0]['average'], expected_score)
                self.assertEqual(len(students), 1)
                self.assertEqual(
                    students[0]['letter_grade'],
                    'F' if expected_score < 60 else 'D',
                )
                dashboard = client.get(f'/dashboard?semester={semester}')
                self.assertEqual(dashboard.status_code, 200)
                self.assertIn(f'Semester {semester.title()}'.encode(), dashboard.data)

        self.assertEqual(client.get('/api/attendance?semester=invalid').status_code, 400)
        self.assertEqual(client.get('/api/exams?semester=invalid').status_code, 400)
        self.assertEqual(client.get('/api/reports/attendance?semester=invalid').status_code, 400)
        self.assertEqual(client.get('/dashboard?semester=invalid').status_code, 400)
        for path in ('/students', '/attendance', '/exams', '/reports'):
            with self.subTest(page=path):
                page = client.get(path)
                self.assertEqual(page.status_code, 200)
                self.assertIn(b'Semester Three', page.data)

    def test_demo_account_is_created_only_for_local_development(self):
        original_environment = self.app.config['ENVIRONMENT']
        original_host = self.app.config['HOST']
        try:
            self.app.config.update(ENVIRONMENT='development', HOST='127.0.0.1')
            create_demo_account(self.app)
            with self.app.app_context():
                demo_admin = User.query.filter_by(username='admin').one()
                self.assertEqual(demo_admin.role, 'Admin')
                self.assertTrue(demo_admin.check_password('admin123'))

            create_demo_account(self.app)
            with self.app.app_context():
                self.assertEqual(User.query.filter_by(username='admin').count(), 1)

            self.app.config['ENVIRONMENT'] = 'production'
            with self.assertRaisesRegex(RuntimeError, 'only be created in development'):
                create_demo_account(self.app)
            self.app.config.update(ENVIRONMENT='development', HOST='0.0.0.0')
            with self.assertRaisesRegex(RuntimeError, 'localhost-only'):
                create_demo_account(self.app)
        finally:
            self.app.config.update(
                ENVIRONMENT=original_environment,
                HOST=original_host,
            )


if __name__ == '__main__':
    unittest.main()
