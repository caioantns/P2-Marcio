"""
Login, organização e papel.

Toda tela do sistema passa por aqui: exige login, descobre a organização do usuário
(request.user.perfil.organizacao) e filtra os dados por ela. Quem não tem perfil não
vê nada; algumas telas exigem o papel de administrador.
"""
from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .forms import OrganizacaoFormMixin
from .models import Organizacao, Perfil


def perfil_do(usuario):
    """
    Perfil do usuário logado. Um superusuário sem perfil (o do createsuperuser)
    ganha um perfil de administrador na primeira organização, para conseguir entrar.
    """
    try:
        return usuario.perfil
    except Perfil.DoesNotExist:
        if not usuario.is_superuser:
            return None
        org = Organizacao.objects.order_by("pk").first() or Organizacao.objects.create(nome="Minha Clínica")
        return Perfil.objects.create(usuario=usuario, organizacao=org, papel=Perfil.Papel.ADMIN)


def _checar(request, papel=None):
    perfil = perfil_do(request.user)
    if perfil is None:
        raise PermissionDenied("Seu usuário não está vinculado a nenhuma organização.")
    if papel and perfil.papel != papel:
        raise PermissionDenied("Seu papel não tem acesso a esta tela.")
    request.perfil = perfil
    request.organizacao = perfil.organizacao
    return perfil


def papel_requerido(papel=None):
    """Decorator para views de função: login + organização (+ papel, se informado)."""

    def decorador(view):
        @wraps(view)
        def interna(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            _checar(request, papel)
            return view(request, *args, **kwargs)

        return interna

    return decorador


organizacao_requerida = papel_requerido()


class OrganizacaoMixin(LoginRequiredMixin):
    """
    Para class-based views. `campo_organizacao` diz como chegar na organização a partir
    do model (ex.: "organizacao" ou "profissional__organizacao").
    """

    campo_organizacao = "organizacao"
    papel = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        _checar(request, self.papel)
        self.organizacao = request.organizacao
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return super().get_queryset().filter(**{self.campo_organizacao: self.organizacao})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # Só os forms do projeto recebem a organização (o form de exclusão é um Form simples)
        if not issubclass(self.get_form_class(), OrganizacaoFormMixin):
            return kwargs
        kwargs["organizacao"] = self.organizacao
        # Na criação de paciente/profissional, o registro já nasce na organização do usuário
        if kwargs.get("instance") is None and self.campo_organizacao == "organizacao":
            kwargs["instance"] = self.model(organizacao=self.organizacao)
        return kwargs


class AdminRequeridoMixin(OrganizacaoMixin):
    papel = Perfil.Papel.ADMIN
