"""
API do dashboard: o mesmo dado da tela, em JSON, para outros clientes (app, BI, planilha).

Reaproveita montar_dashboard() em vez de duplicar consultas, então o isolamento
por organização, o filtro de período e a regra por papel são exatamente os mesmos.
"""
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .dashboard import montar_dashboard
from .forms import PeriodoForm
from .permissoes import perfil_do


class TemOrganizacao(BasePermission):
    message = "Seu usuário não está vinculado a nenhuma organização."

    def has_permission(self, request, view):
        return perfil_do(request.user) is not None


class DashboardApi(APIView):
    permission_classes = [IsAuthenticated, TemOrganizacao]

    def get(self, request):
        perfil = perfil_do(request.user)
        form = PeriodoForm(request.query_params)
        if not form.is_valid():
            return Response({"erros": form.errors}, status=status.HTTP_400_BAD_REQUEST)
        dados = montar_dashboard(perfil.organizacao, form, mostra_series=perfil.eh_admin)
        dados["organizacao"] = perfil.organizacao.nome
        return Response(dados)
