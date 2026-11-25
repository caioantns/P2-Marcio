from django.urls import path

from . import api_views, views

urlpatterns = [
    path("", views.agenda_dia, name="agenda_dia"),

    # P2 — Dashboard e relatórios
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/exportar.csv", views.exportar_csv, name="dashboard_csv"),
    path("api/dashboard/", api_views.DashboardApi.as_view(), name="api_dashboard"),

    path("consultas/", views.ConsultaListView.as_view(), name="consulta_lista"),
    path("consultas/nova/", views.ConsultaCreateView.as_view(), name="consulta_nova"),
    path("consultas/<int:pk>/", views.ConsultaDetailView.as_view(), name="consulta_detalhe"),
    path("consultas/<int:pk>/editar/", views.ConsultaUpdateView.as_view(), name="consulta_editar"),
    path("consultas/<int:pk>/excluir/", views.ConsultaDeleteView.as_view(), name="consulta_excluir"),
    path("consultas/<int:pk>/status/", views.consulta_alterar_status, name="consulta_status"),

    path("pacientes/", views.PacienteListView.as_view(), name="paciente_lista"),
    path("pacientes/novo/", views.PacienteCreateView.as_view(), name="paciente_novo"),
    path("pacientes/<int:pk>/", views.PacienteDetailView.as_view(), name="paciente_detalhe"),
    path("pacientes/<int:pk>/editar/", views.PacienteUpdateView.as_view(), name="paciente_editar"),
    path("pacientes/<int:pk>/excluir/", views.PacienteDeleteView.as_view(), name="paciente_excluir"),

    path("profissionais/", views.ProfissionalListView.as_view(), name="profissional_lista"),
    path("profissionais/novo/", views.ProfissionalCreateView.as_view(), name="profissional_novo"),
    path("profissionais/<int:pk>/", views.ProfissionalDetailView.as_view(), name="profissional_detalhe"),
    path("profissionais/<int:pk>/editar/", views.ProfissionalUpdateView.as_view(), name="profissional_editar"),
    path("profissionais/<int:pk>/excluir/", views.ProfissionalDeleteView.as_view(), name="profissional_excluir"),

    path("disponibilidades/nova/", views.DisponibilidadeCreateView.as_view(), name="disponibilidade_nova"),
    path("disponibilidades/<int:pk>/editar/", views.DisponibilidadeUpdateView.as_view(), name="disponibilidade_editar"),
    path("disponibilidades/<int:pk>/excluir/", views.DisponibilidadeDeleteView.as_view(), name="disponibilidade_excluir"),
]
