from .permissoes import perfil_do


def perfil(request):
    """Deixa o perfil (organização e papel) disponível em todos os templates."""
    if not request.user.is_authenticated:
        return {}
    p = getattr(request, "perfil", None) or perfil_do(request.user)
    return {"perfil": p, "eh_admin": bool(p and p.eh_admin)}
