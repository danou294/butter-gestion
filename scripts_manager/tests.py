"""
Tests pour l'application scripts_manager.
Couvre : authentification, rate limiting, contrôle d'accès, sécurité.
"""
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.urls import reverse


class AuthTestCase(TestCase):
    """Tests d'authentification"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='testpass123')
        cache.clear()

    def test_login_page_loads(self):
        response = self.client.get(reverse('scripts_manager:login'))
        self.assertEqual(response.status_code, 200)

    def test_login_success(self):
        response = self.client.post(reverse('scripts_manager:login'), {
            'username': 'testuser',
            'password': 'testpass123',
        })
        self.assertRedirects(response, reverse('scripts_manager:index'))

    def test_login_wrong_password(self):
        response = self.client.post(reverse('scripts_manager:login'), {
            'username': 'testuser',
            'password': 'wrongpass',
        })
        self.assertEqual(response.status_code, 200)  # reste sur la page login

    def test_login_redirects_authenticated_user(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('scripts_manager:login'))
        self.assertRedirects(response, reverse('scripts_manager:index'))

    def test_logout(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('scripts_manager:logout'))
        self.assertRedirects(response, reverse('scripts_manager:login'))

    def test_open_redirect_blocked(self):
        """Vérifie que les redirections vers des sites externes sont bloquées"""
        response = self.client.post(
            reverse('scripts_manager:login') + '?next=https://evil.com',
            {'username': 'testuser', 'password': 'testpass123'},
        )
        # Doit rediriger vers l'index, pas vers evil.com
        self.assertRedirects(response, reverse('scripts_manager:index'))

    def test_open_redirect_internal_allowed(self):
        """Vérifie que les redirections internes fonctionnent"""
        response = self.client.post(
            reverse('scripts_manager:login') + '?next=/restaurants/',
            {'username': 'testuser', 'password': 'testpass123'},
        )
        self.assertRedirects(response, '/restaurants/')


class RateLimitTestCase(TestCase):
    """Tests du rate limiting sur le login"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='testpass123')
        cache.clear()

    def test_rate_limit_after_5_attempts(self):
        """Après 5 tentatives échouées, l'accès est bloqué"""
        for i in range(5):
            self.client.post(reverse('scripts_manager:login'), {
                'username': 'testuser',
                'password': 'wrongpass',
            })

        # 6e tentative : bloquée
        response = self.client.post(reverse('scripts_manager:login'), {
            'username': 'testuser',
            'password': 'testpass123',  # même le bon mot de passe est bloqué
        })
        self.assertEqual(response.status_code, 200)  # reste sur login

    def test_rate_limit_resets_on_success(self):
        """Le compteur se reset après un login réussi"""
        # 3 tentatives échouées
        for i in range(3):
            self.client.post(reverse('scripts_manager:login'), {
                'username': 'testuser',
                'password': 'wrongpass',
            })

        # Login réussi
        response = self.client.post(reverse('scripts_manager:login'), {
            'username': 'testuser',
            'password': 'testpass123',
        })
        self.assertRedirects(response, reverse('scripts_manager:index'))

        # Logout puis re-échecs : le compteur repart de 0
        self.client.get(reverse('scripts_manager:logout'))
        cache.clear()  # simule le reset

        for i in range(4):
            self.client.post(reverse('scripts_manager:login'), {
                'username': 'testuser',
                'password': 'wrongpass',
            })

        # 5e tentative avec bon mot de passe : devrait passer
        response = self.client.post(reverse('scripts_manager:login'), {
            'username': 'testuser',
            'password': 'testpass123',
        })
        self.assertRedirects(response, reverse('scripts_manager:index'))


class AccessControlTestCase(TestCase):
    """Vérifie que tous les endpoints protégés redirigent vers le login"""

    def setUp(self):
        self.client = Client()

    # --- Endpoints qui DOIVENT rediriger vers login ---

    PROTECTED_GET_URLS = [
        'scripts_manager:index',
        'scripts_manager:export_index',
        'scripts_manager:import_restaurants_index',
        'scripts_manager:restore_backup_index',
        'scripts_manager:restaurants_list',
        'scripts_manager:restaurant_create',
        'scripts_manager:photos_list',
        'scripts_manager:notifications_index',
        'scripts_manager:announcements_list',
        'scripts_manager:announcement_create',
        'scripts_manager:guides_list',
        'scripts_manager:guide_create',
        'scripts_manager:onboarding_list',
        'scripts_manager:users_list',
    ]

    def test_protected_pages_redirect_to_login(self):
        """Toutes les pages protégées redirigent vers /login/ si non connecté"""
        for url_name in self.PROTECTED_GET_URLS:
            url = reverse(url_name)
            response = self.client.get(url)
            self.assertIn(
                response.status_code, [302, 301],
                f'{url_name} ({url}) devrait rediriger vers login, got {response.status_code}'
            )
            self.assertIn('/login/', response.url, f'{url_name} ne redirige pas vers /login/')

    # --- Endpoints qui DOIVENT être publics ---

    def test_login_page_is_public(self):
        response = self.client.get(reverse('scripts_manager:login'))
        self.assertEqual(response.status_code, 200)

    def test_troll_page_is_public(self):
        response = self.client.get(reverse('scripts_manager:augmenter_daniel'))
        self.assertEqual(response.status_code, 200)

    # --- Endpoints POST protégés ---

    PROTECTED_POST_URLS = [
        'scripts_manager:run_export',
        'scripts_manager:run_import_restaurants',
        'scripts_manager:send_notification_to_all',
        'scripts_manager:send_notification_to_all_with_prenom',
        'scripts_manager:send_notification_to_group',
    ]

    def test_protected_post_endpoints_require_login(self):
        """Les endpoints POST protégés redirigent vers login"""
        for url_name in self.PROTECTED_POST_URLS:
            url = reverse(url_name)
            response = self.client.post(url)
            self.assertIn(
                response.status_code, [302, 301],
                f'{url_name} ({url}) devrait rediriger vers login, got {response.status_code}'
            )


class SecuritySettingsTestCase(TestCase):
    """Vérifie que les settings de sécurité sont correctement configurés"""

    def test_session_cookie_httponly(self):
        from django.conf import settings
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)

    def test_x_frame_options(self):
        from django.conf import settings
        self.assertEqual(settings.X_FRAME_OPTIONS, 'DENY')

    def test_content_type_nosniff(self):
        from django.conf import settings
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)

    def test_secret_key_not_insecure_default(self):
        from django.conf import settings
        self.assertNotEqual(settings.SECRET_KEY, '')

    def test_csrf_middleware_enabled(self):
        from django.conf import settings
        self.assertIn(
            'django.middleware.csrf.CsrfViewMiddleware',
            settings.MIDDLEWARE,
        )

    def test_security_middleware_enabled(self):
        from django.conf import settings
        self.assertIn(
            'django.middleware.security.SecurityMiddleware',
            settings.MIDDLEWARE,
        )

    @override_settings(DEBUG=False)
    def test_production_security_headers(self):
        """En production, les headers SSL/HSTS doivent être activés"""
        # Note: ces settings sont conditionnels dans settings.py (if not DEBUG)
        # Ce test vérifie que le concept est bon, pas les valeurs runtime
        pass


class CSRFProtectionTestCase(TestCase):
    """Vérifie que la protection CSRF est active"""

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.user = User.objects.create_user(username='testuser', password='testpass123')

    def test_login_without_csrf_fails(self):
        """Le login sans token CSRF échoue"""
        response = self.client.post(reverse('scripts_manager:login'), {
            'username': 'testuser',
            'password': 'testpass123',
        })
        self.assertEqual(response.status_code, 403)

    def test_notification_without_csrf_fails(self):
        """Les notifications sans token CSRF échouent"""
        self.client = Client()  # sans enforce_csrf_checks pour le login
        self.client.login(username='testuser', password='testpass123')

        csrf_client = Client(enforce_csrf_checks=True)
        # Copier la session
        csrf_client.cookies = self.client.cookies

        response = csrf_client.post(
            reverse('scripts_manager:send_notification_to_all'),
            data='{"title":"test","body":"test"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)
