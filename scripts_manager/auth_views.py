from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods


def register_view(request):
    """Vue pour l'inscription"""
    if request.user.is_authenticated:
        return redirect('scripts_manager:index')
    
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'Compte créé avec succès pour {username} !')
            # Connecter automatiquement l'utilisateur après l'inscription
            login(request, user)
            return redirect('scripts_manager:index')
        else:
            messages.error(request, 'Erreur lors de la création du compte. Veuillez vérifier les informations.')
    else:
        form = UserCreationForm()
    
    return render(request, 'scripts_manager/auth/register.html', {'form': form})


@require_http_methods(["GET", "POST"])
def login_view(request):
    """Vue pour la connexion"""
    if request.user.is_authenticated:
        return redirect('scripts_manager:index')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            messages.success(request, f'Bienvenue, {username} !')
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('scripts_manager:index')
        else:
            messages.error(request, 'Nom d\'utilisateur ou mot de passe incorrect.')
    
    return render(request, 'scripts_manager/auth/login.html')


@login_required
def logout_view(request):
    """Vue pour la déconnexion"""
    from django.contrib.auth import logout
    logout(request)
    messages.success(request, 'Vous avez été déconnecté avec succès.')
    return redirect('scripts_manager:login')

