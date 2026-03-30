from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import redirect


def role_required(allowed_roles):
    """Decorator to require an authenticated user with an Operario having a role in allowed_roles.
    If not authenticated, redirects to login. If role mismatch, returns 403.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('/accounts/login/?next=' + request.path)
            operario = getattr(request.user, 'operario', None)
            if not operario or operario.role not in allowed_roles:
                return HttpResponseForbidden('No tienes permisos para acceder a esta página.')
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
