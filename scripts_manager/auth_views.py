from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.utils.http import url_has_allowed_host_and_scheme
from django.core.cache import cache


# Rate limiting : max 5 tentatives par IP sur 5 minutes
LOGIN_MAX_ATTEMPTS = 5
LOGIN_COOLDOWN = 300  # secondes


def _get_client_ip(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def register_view(request):
    """Vue pour l'inscription - DÉSACTIVÉE"""
    from django.http import Http404
    raise Http404("L'inscription n'est plus disponible.")


@require_http_methods(["GET", "POST"])
def login_view(request):
    """Vue pour la connexion"""
    if request.user.is_authenticated:
        return redirect('scripts_manager:index')

    if request.method == 'POST':
        # Rate limiting par IP
        ip = _get_client_ip(request)
        cache_key = f'login_attempts:{ip}'
        attempts = cache.get(cache_key, 0)

        if attempts >= LOGIN_MAX_ATTEMPTS:
            messages.error(request, 'Trop de tentatives. Réessayez dans quelques minutes.')
            return render(request, 'scripts_manager/auth/login.html')

        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user is not None:
            cache.delete(cache_key)  # Reset on success
            login(request, user)
            messages.success(request, f'Bienvenue, {username} !')
            next_url = request.GET.get('next')
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect('scripts_manager:index')
        else:
            cache.set(cache_key, attempts + 1, LOGIN_COOLDOWN)
            remaining = LOGIN_MAX_ATTEMPTS - attempts - 1
            if remaining > 0:
                messages.error(request, f'Identifiants incorrects. {remaining} tentative(s) restante(s).')
            else:
                messages.error(request, 'Trop de tentatives. Réessayez dans quelques minutes.')

    return render(request, 'scripts_manager/auth/login.html')


@login_required
def logout_view(request):
    """Vue pour la déconnexion"""
    from django.contrib.auth import logout
    logout(request)
    messages.success(request, 'Vous avez été déconnecté avec succès.')
    return redirect('scripts_manager:login')
