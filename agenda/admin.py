from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import Consulta, Disponibilidade, Organizacao, Paciente, Perfil, Profissional


@admin.register(Organizacao)
class OrganizacaoAdmin(admin.ModelAdmin):
    list_display = ("nome", "criado_em")
    search_fields = ("nome",)


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ("usuario", "organizacao", "papel")
    list_filter = ("organizacao", "papel")
    list_select_related = ("usuario", "organizacao")


class PerfilInline(admin.StackedInline):
    model = Perfil
    can_delete = False
    verbose_name_plural = "perfil na clínica"


# Mostra organização e papel direto na tela do usuário
admin.site.unregister(User)


@admin.register(User)
class UsuarioAdmin(UserAdmin):
    inlines = [PerfilInline]


@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ("nome", "cpf", "telefone", "email", "organizacao")
    list_filter = ("organizacao",)
    list_select_related = ("organizacao",)
    search_fields = ("nome", "cpf", "email")


class DisponibilidadeInline(admin.TabularInline):
    model = Disponibilidade
    extra = 1


@admin.register(Profissional)
class ProfissionalAdmin(admin.ModelAdmin):
    list_display = ("nome", "especialidade", "registro", "duracao_consulta", "ativo", "organizacao")
    list_filter = ("organizacao", "ativo", "especialidade")
    list_select_related = ("organizacao",)
    search_fields = ("nome", "registro")
    inlines = [DisponibilidadeInline]


@admin.register(Disponibilidade)
class DisponibilidadeAdmin(admin.ModelAdmin):
    list_display = ("profissional", "dia_semana", "hora_inicio", "hora_fim")
    list_filter = ("dia_semana", "profissional")
    list_select_related = ("profissional",)  # o __str__ usa profissional.nome: evita N+1


@admin.register(Consulta)
class ConsultaAdmin(admin.ModelAdmin):
    list_display = ("data", "hora_inicio", "hora_fim", "paciente", "profissional", "status")
    list_filter = ("status", "profissional__organizacao", "profissional", "data")
    list_select_related = ("paciente", "profissional")
    search_fields = ("paciente__nome", "profissional__nome")
    date_hierarchy = "data"
    autocomplete_fields = ("paciente",)
