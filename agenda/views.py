import csv
from datetime import date, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError, Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .forms import (
    ConsultaForm,
    DisponibilidadeForm,
    FiltroConsultaForm,
    PacienteForm,
    ProfissionalForm,
)
from .dashboard import consultas_da_organizacao, filtrar_periodo, montar_dashboard, periodo_do
from .models import Consulta, Disponibilidade, Paciente, Profissional
from .permissoes import AdminRequeridoMixin, OrganizacaoMixin, organizacao_requerida, papel_requerido


def _data_da_url(request, padrao=None):
    return parse_date(request.GET.get("data") or "") or padrao or timezone.localdate()


def _minutos(hora):
    return hora.hour * 60 + hora.minute


# ----------------------------------------------------------------------
# Agenda do dia (página inicial)
# ----------------------------------------------------------------------
@organizacao_requerida
def agenda_dia(request):
    org = request.organizacao
    dia = _data_da_url(request)
    consultas = (
        Consulta.objects.filter(data=dia, profissional__organizacao=org)
        .select_related("paciente", "profissional")
        .order_by("hora_inicio")
    )
    disponibilidades = Disponibilidade.objects.filter(
        dia_semana=dia.weekday(), profissional__organizacao=org
    )

    ids = set(consultas.values_list("profissional_id", flat=True)) | set(
        disponibilidades.filter(profissional__ativo=True).values_list("profissional_id", flat=True)
    )
    profissionais = Profissional.objects.filter(pk__in=ids, organizacao=org)

    # Janela de horário exibida: das 8h às 18h, ampliada se houver algo fora disso
    horarios = [(d.hora_inicio, d.hora_fim) for d in disponibilidades] + [
        (c.hora_inicio, c.hora_fim) for c in consultas
    ]
    inicio_min = min([8 * 60] + [_minutos(i) for i, _ in horarios]) // 60 * 60
    fim_min = -(-max([18 * 60] + [_minutos(f) for _, f in horarios]) // 60) * 60
    total = fim_min - inicio_min

    def posicao(ini, fim):
        return {
            "topo": round((_minutos(ini) - inicio_min) / total * 100, 3),
            "altura": round((_minutos(fim) - _minutos(ini)) / total * 100, 3),
        }

    colunas = []
    for prof in profissionais:
        colunas.append(
            {
                "profissional": prof,
                "faixas": [
                    posicao(d.hora_inicio, d.hora_fim)
                    for d in disponibilidades
                    if d.profissional_id == prof.pk
                ],
                "consultas": [
                    {"consulta": c, **posicao(c.hora_inicio, c.hora_fim)}
                    for c in consultas
                    if c.profissional_id == prof.pk
                ],
            }
        )

    horas = [
        {"rotulo": f"{m // 60:02d}:00", "topo": round((m - inicio_min) / total * 100, 3)}
        for m in range(inicio_min, fim_min, 60)
    ]

    resumo = {
        "total": consultas.exclude(status=Consulta.Status.CANCELADA).count(),
        "realizadas": consultas.filter(status=Consulta.Status.REALIZADA).count(),
        "canceladas": consultas.filter(status=Consulta.Status.CANCELADA).count(),
    }

    return render(
        request,
        "agenda/agenda_dia.html",
        {
            "dia": dia,
            "hoje": timezone.localdate(),
            "anterior": dia - timedelta(days=1),
            "proximo": dia + timedelta(days=1),
            "colunas": colunas,
            "horas": horas,
            "altura_px": int(total * 1.6),  # 1,6 px por minuto
            "resumo": resumo,
        },
    )


# ----------------------------------------------------------------------
# Mixins reaproveitados
# ----------------------------------------------------------------------
class FormGenericoMixin:
    template_name = "agenda/form.html"
    titulo = ""
    voltar_url = None

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["titulo"] = self.titulo
        ctx["voltar_url"] = self.get_voltar_url()
        return ctx

    def get_voltar_url(self):
        if getattr(self, "object", None) and self.object.pk:
            return self.object.get_absolute_url()
        return self.voltar_url


class ExclusaoProtegidaMixin:
    """Mostra uma mensagem amigável quando o registro tem consultas ligadas a ele."""

    template_name = "agenda/confirmar_exclusao.html"
    mensagem_protegido = "Esse registro possui consultas vinculadas e não pode ser excluído."

    def form_valid(self, form):
        try:
            nome = str(self.object)
            resposta = super().form_valid(form)
            messages.success(self.request, f"{nome} foi excluído.")
            return resposta
        except ProtectedError:
            messages.error(self.request, self.mensagem_protegido)
            return HttpResponseRedirect(self.object.get_absolute_url())


# ----------------------------------------------------------------------
# Pacientes
# ----------------------------------------------------------------------
class PacienteListView(OrganizacaoMixin, ListView):
    model = Paciente
    paginate_by = 20
    template_name = "agenda/paciente_lista.html"

    def get_queryset(self):
        qs = super().get_queryset()
        busca = self.request.GET.get("q", "").strip()
        if busca:
            digitos = "".join(c for c in busca if c.isdigit())
            filtro = Q(nome__icontains=busca) | Q(email__icontains=busca)
            if digitos:
                filtro |= Q(cpf__contains=digitos) | Q(telefone__contains=busca)
            qs = qs.filter(filtro)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        busca = self.request.GET.get("q", "")
        ctx["parametros"] = urlencode({"q": busca}) if busca else ""
        return ctx


class PacienteDetailView(OrganizacaoMixin, DetailView):
    model = Paciente
    template_name = "agenda/paciente_detalhe.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        hoje = timezone.localdate()
        consultas = self.object.consultas.select_related("profissional")
        ctx["proximas"] = consultas.filter(data__gte=hoje).order_by("data", "hora_inicio")
        ctx["historico"] = consultas.filter(data__lt=hoje).order_by("-data", "-hora_inicio")
        return ctx


class PacienteCreateView(OrganizacaoMixin, SuccessMessageMixin, FormGenericoMixin, CreateView):
    model = Paciente
    form_class = PacienteForm
    titulo = "Novo paciente"
    voltar_url = reverse_lazy("paciente_lista")
    success_message = "Paciente %(nome)s cadastrado."


class PacienteUpdateView(OrganizacaoMixin, SuccessMessageMixin, FormGenericoMixin, UpdateView):
    model = Paciente
    form_class = PacienteForm
    titulo = "Editar paciente"
    success_message = "Dados de %(nome)s atualizados."


class PacienteDeleteView(AdminRequeridoMixin, ExclusaoProtegidaMixin, DeleteView):
    model = Paciente
    success_url = reverse_lazy("paciente_lista")
    mensagem_protegido = (
        "Esse paciente tem consultas registradas e não pode ser excluído. "
        "Cancele ou exclua as consultas primeiro."
    )


# ----------------------------------------------------------------------
# Profissionais
# ----------------------------------------------------------------------
class ProfissionalListView(OrganizacaoMixin, ListView):
    model = Profissional
    template_name = "agenda/profissional_lista.html"

    def get_queryset(self):
        return super().get_queryset().prefetch_related("disponibilidades")


class ProfissionalDetailView(OrganizacaoMixin, DetailView):
    model = Profissional
    template_name = "agenda/profissional_detalhe.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        dia = _data_da_url(self.request)
        ctx["dia"] = dia
        ctx["livres"] = self.object.horarios_livres(dia)
        ctx["disponibilidades"] = self.object.disponibilidades.all()
        ctx["proximas"] = (
            self.object.consultas.filter(data__gte=timezone.localdate())
            .exclude(status=Consulta.Status.CANCELADA)
            .select_related("paciente")[:10]
        )
        return ctx


class ProfissionalCreateView(AdminRequeridoMixin, SuccessMessageMixin, FormGenericoMixin, CreateView):
    model = Profissional
    form_class = ProfissionalForm
    titulo = "Novo profissional"
    voltar_url = reverse_lazy("profissional_lista")
    success_message = "%(nome)s cadastrado. Agora adicione os horários de atendimento."


class ProfissionalUpdateView(AdminRequeridoMixin, SuccessMessageMixin, FormGenericoMixin, UpdateView):
    model = Profissional
    form_class = ProfissionalForm
    titulo = "Editar profissional"
    success_message = "Dados de %(nome)s atualizados."


class ProfissionalDeleteView(AdminRequeridoMixin, ExclusaoProtegidaMixin, DeleteView):
    model = Profissional
    success_url = reverse_lazy("profissional_lista")
    mensagem_protegido = (
        "Esse profissional tem consultas registradas e não pode ser excluído. "
        "Para parar de receber agendamentos, marque-o como inativo."
    )


# ----------------------------------------------------------------------
# Disponibilidades
# ----------------------------------------------------------------------
class DisponibilidadeMixin(AdminRequeridoMixin, SuccessMessageMixin, FormGenericoMixin):
    model = Disponibilidade
    campo_organizacao = "profissional__organizacao"
    form_class = DisponibilidadeForm
    success_message = "Horário de atendimento salvo."

    def get_success_url(self):
        return self.object.profissional.get_absolute_url()

    def get_voltar_url(self):
        if getattr(self, "object", None) and self.object.pk:
            return self.object.profissional.get_absolute_url()
        prof_id = self.request.GET.get("profissional")
        if prof_id:
            return reverse("profissional_detalhe", args=[prof_id])
        return reverse("profissional_lista")


class DisponibilidadeCreateView(DisponibilidadeMixin, CreateView):
    titulo = "Novo horário de atendimento"

    def get_initial(self):
        return {"profissional": self.request.GET.get("profissional")}


class DisponibilidadeUpdateView(DisponibilidadeMixin, UpdateView):
    titulo = "Editar horário de atendimento"


class DisponibilidadeDeleteView(AdminRequeridoMixin, DeleteView):
    model = Disponibilidade
    campo_organizacao = "profissional__organizacao"
    template_name = "agenda/confirmar_exclusao.html"

    def get_success_url(self):
        messages.success(self.request, "Horário de atendimento removido.")
        return self.object.profissional.get_absolute_url()


# ----------------------------------------------------------------------
# Consultas
# ----------------------------------------------------------------------
class ConsultaListView(OrganizacaoMixin, ListView):
    model = Consulta
    campo_organizacao = "profissional__organizacao"
    paginate_by = 25
    template_name = "agenda/consulta_lista.html"

    def get_queryset(self):
        qs = super().get_queryset().select_related("paciente", "profissional")
        self.filtro = FiltroConsultaForm(self.request.GET or None, organizacao=self.organizacao)
        if self.filtro.is_valid():
            f = self.filtro.cleaned_data
            if f["data"]:
                qs = qs.filter(data=f["data"])
            if f["profissional"]:
                qs = qs.filter(profissional=f["profissional"])
            if f["status"]:
                qs = qs.filter(status=f["status"])
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filtro"] = self.filtro
        parametros = self.request.GET.copy()
        parametros.pop("page", None)
        ctx["parametros"] = parametros.urlencode()
        return ctx


class ConsultaDetailView(OrganizacaoMixin, DetailView):
    model = Consulta
    campo_organizacao = "profissional__organizacao"
    template_name = "agenda/consulta_detalhe.html"

    def get_queryset(self):
        return super().get_queryset().select_related("paciente", "profissional")


class ConsultaCreateView(OrganizacaoMixin, SuccessMessageMixin, FormGenericoMixin, CreateView):
    model = Consulta
    campo_organizacao = "profissional__organizacao"
    form_class = ConsultaForm
    titulo = "Nova consulta"
    voltar_url = reverse_lazy("agenda_dia")
    success_message = "Consulta agendada."

    def get_initial(self):
        # Permite chegar aqui já com profissional, data e horário preenchidos
        # (links de "horários livres" na página do profissional)
        return {
            campo: self.request.GET.get(campo)
            for campo in ("profissional", "paciente", "data", "hora_inicio")
            if self.request.GET.get(campo)
        }

    def get_success_url(self):
        return f"{reverse('agenda_dia')}?data={self.object.data:%Y-%m-%d}"


class ConsultaUpdateView(OrganizacaoMixin, SuccessMessageMixin, FormGenericoMixin, UpdateView):
    model = Consulta
    campo_organizacao = "profissional__organizacao"
    form_class = ConsultaForm
    titulo = "Editar consulta"
    success_message = "Consulta atualizada."


class ConsultaDeleteView(AdminRequeridoMixin, DeleteView):
    model = Consulta
    campo_organizacao = "profissional__organizacao"
    template_name = "agenda/confirmar_exclusao.html"

    def get_success_url(self):
        messages.success(self.request, "Consulta excluída.")
        return reverse("consulta_lista")


@require_POST
@organizacao_requerida
def consulta_alterar_status(request, pk):
    consulta = get_object_or_404(Consulta, pk=pk, profissional__organizacao=request.organizacao)
    novo = request.POST.get("status")
    if novo not in Consulta.Status.values:
        messages.error(request, "Status inválido.")
    else:
        consulta.status = novo
        try:
            consulta.save()
            messages.success(request, f"Consulta marcada como {consulta.get_status_display().lower()}.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    proximo = request.POST.get("proximo", "")
    if not url_has_allowed_host_and_scheme(proximo, allowed_hosts={request.get_host()}):
        proximo = consulta.get_absolute_url()
    return redirect(proximo)


# ----------------------------------------------------------------------
# P2 — Dashboard e relatórios (Aula 17)
# ----------------------------------------------------------------------
def _atalhos_de_periodo(hoje):
    """Links prontos para os períodos que o dono mais consulta."""
    inicio_mes = hoje.replace(day=1)
    tres_meses = (inicio_mes - timedelta(days=62)).replace(day=1)
    return [
        ("Este mês", {"inicio": inicio_mes, "fim": hoje}),
        ("Últimos 3 meses", {"inicio": tres_meses, "fim": hoje}),
        ("Este ano", {"inicio": date(hoje.year, 1, 1), "fim": date(hoje.year, 12, 31)}),
        ("Todo o período", {}),
    ]


@organizacao_requerida
def dashboard(request):
    perfil = request.perfil
    form = periodo_do(request)
    # Dashboard por papel: o operador não vê as séries por período nem exporta
    mostra_series = perfil.eh_admin
    dados = montar_dashboard(request.organizacao, form, mostra_series=mostra_series)

    parametros = request.GET.copy()
    atalhos = []
    for rotulo, valores in _atalhos_de_periodo(timezone.localdate()):
        p = {k: v.isoformat() for k, v in valores.items()}
        if parametros.get("agrupar"):
            p["agrupar"] = parametros["agrupar"]
        ativo = (parametros.get("inicio") or None) == p.get("inicio") and (
            parametros.get("fim") or None
        ) == p.get("fim")
        atalhos.append({"rotulo": rotulo, "query": urlencode(p), "ativo": ativo})

    contexto = {
        **dados,
        "form": form,
        "mostra_series": mostra_series,
        "atalhos": atalhos,
        "parametros": parametros.urlencode(),
        "soma_serie": sum(p["total"] for p in dados.get("serie", [])),
        # json_script escreve o JSON de forma segura na página; o Chart.js lê dali
        "dados_graficos": {
            "serie": dados.get("serie", []),
            "dias": dados["por_dia_semana"],
        },
    }
    return render(request, "agenda/dashboard.html", contexto)


def _celula_segura(valor):
    """Célula que começa com = + - @ pode virar fórmula no Excel (CSV injection)."""
    texto = "" if valor is None else str(valor)
    if texto[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + texto
    return texto


@papel_requerido("admin")
def exportar_csv(request):
    form = periodo_do(request)
    # A mesma base do dashboard: organização + período. select_related evita o N+1.
    qs = filtrar_periodo(
        request,
        consultas_da_organizacao(request.organizacao)
        .select_related("paciente", "profissional")
        .order_by("data", "hora_inicio"),
    )

    nome = "consultas"
    if form.is_valid():
        if form.cleaned_data["inicio"]:
            nome += f"_de_{form.cleaned_data['inicio']:%Y-%m-%d}"
        if form.cleaned_data["fim"]:
            nome += f"_ate_{form.cleaned_data['fim']:%Y-%m-%d}"

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{nome}.csv"'
    resp.write("﻿")  # BOM: faz o Excel reconhecer os acentos
    w = csv.writer(resp, delimiter=";")  # Excel em português usa ; como separador
    w.writerow(["Data", "Início", "Fim", "Paciente", "CPF", "Telefone",
                "Profissional", "Especialidade", "Status", "Observações"])
    for c in qs:
        w.writerow([_celula_segura(v) for v in (
            f"{c.data:%d/%m/%Y}", f"{c.hora_inicio:%H:%M}", f"{c.hora_fim:%H:%M}",
            c.paciente.nome, c.paciente.cpf_formatado, c.paciente.telefone,
            c.profissional.nome, c.profissional.especialidade,
            c.get_status_display(), c.observacoes,
        )])
    return resp
