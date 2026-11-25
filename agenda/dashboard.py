"""
Métricas do dashboard (Aula 17).

As quatro perguntas que o dono da clínica faz toda semana:

  1. Quantas consultas tivemos e quantas foram canceladas?   -> KPIs      (aggregate)
  2. Quais profissionais mais atendem?                        -> ranking   (values + annotate + order_by)
  3. O movimento está crescendo ou caindo?                    -> série     (TruncMonth/TruncWeek/TruncDay)
  4. Quais dias da semana são mais cheios?                    -> distribuição (ExtractIsoWeekDay)

Regra de ouro: toda métrica parte de `base`, que já vem filtrada pela organização
e pelo período. Assim o isolamento entre clínicas e o filtro valem para todos os
cartões e gráficos de uma vez. A view HTML e a API chamam as mesmas funções.
"""
from datetime import date, datetime, timedelta

from django.db.models import Count, Q
from django.db.models.functions import ExtractIsoWeekDay, TruncDay, TruncMonth, TruncWeek

from .forms import PeriodoForm
from .models import Consulta

AGENDADA = Consulta.Status.AGENDADA
REALIZADA = Consulta.Status.REALIZADA
CANCELADA = Consulta.Status.CANCELADA

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
TRUNCAR = {"mes": TruncMonth, "semana": TruncWeek, "dia": TruncDay}


# ----------------------------------------------------------------------
# Base filtrada
# ----------------------------------------------------------------------
def consultas_da_organizacao(org):
    """Primeira linha de toda métrica: esquecer este filtro = dado de outra clínica no gráfico."""
    return Consulta.objects.filter(profissional__organizacao=org)


def periodo_do(request):
    """PeriodoForm já validado a partir da querystring (?inicio=...&fim=...&agrupar=...)."""
    form = PeriodoForm(request.GET)
    form.is_valid()
    return form


def filtrar_periodo(request, qs):
    form = periodo_do(request)
    if form.is_valid():
        if form.cleaned_data["inicio"]:
            qs = qs.filter(data__gte=form.cleaned_data["inicio"])
        if form.cleaned_data["fim"]:
            qs = qs.filter(data__lte=form.cleaned_data["fim"])
    return qs


def _contagens_por_status():
    """Count com filter= conta só as linhas que atendem à condição, tudo numa consulta só."""
    return {
        "total": Count("id"),
        "agendadas": Count("id", filter=Q(status=AGENDADA)),
        "realizadas": Count("id", filter=Q(status=REALIZADA)),
        "canceladas": Count("id", filter=Q(status=CANCELADA)),
    }


def _percentual(parte, todo):
    return round(parte * 100 / todo, 1) if todo else 0.0


# ----------------------------------------------------------------------
# 1. KPIs (aggregate -> um dicionário)
# ----------------------------------------------------------------------
def kpis(base):
    k = base.aggregate(
        **_contagens_por_status(),
        pacientes=Count("paciente", distinct=True, filter=~Q(status=CANCELADA)),
    )
    k["taxa_cancelamento"] = _percentual(k["canceladas"], k["total"])
    return k


# ----------------------------------------------------------------------
# 2. Ranking (values -> agrupa, annotate -> conta, order_by -> ordena, [:5] -> fatia)
# ----------------------------------------------------------------------
def ranking_profissionais(base, limite=5):
    linhas = list(
        base.values("profissional_id", "profissional__nome", "profissional__especialidade")
        .annotate(**_contagens_por_status())
        .order_by("-realizadas", "-total", "profissional__nome")[:limite]
    )
    maior = max((linha["realizadas"] for linha in linhas), default=0)
    for linha in linhas:
        linha["taxa_cancelamento"] = _percentual(linha["canceladas"], linha["total"])
        # Largura da barrinha na tabela (0 a 100), relativa ao primeiro colocado
        linha["barra"] = _percentual(linha["realizadas"], maior)
    return linhas


# ----------------------------------------------------------------------
# 3. Série no tempo (Trunc* agrupa datas; order_by no fim para não embaralhar)
# ----------------------------------------------------------------------
def _inicio_do_periodo(d, agrupar):
    if agrupar == "mes":
        return d.replace(day=1)
    if agrupar == "semana":
        return d - timedelta(days=d.weekday())  # segunda-feira, igual ao TruncWeek
    return d


def _proximo_periodo(d, agrupar):
    if agrupar == "mes":
        return date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return d + timedelta(days=7 if agrupar == "semana" else 1)


def _rotulo(d, agrupar):
    if agrupar == "mes":
        return f"{MESES[d.month - 1]}/{d.year}"
    return f"{d:%d/%m}"


def serie_temporal(base, agrupar="mes", inicio=None, fim=None):
    agrupar = agrupar if agrupar in TRUNCAR else "mes"
    linhas = (
        base.annotate(periodo=TRUNCAR[agrupar]("data"))
        .values("periodo")
        .annotate(**_contagens_por_status())
        .order_by("periodo")
    )
    por_periodo = {}
    for linha in linhas:
        p = linha["periodo"]
        if isinstance(p, datetime):  # alguns bancos devolvem datetime no Trunc
            p = p.date()
        por_periodo[p] = linha

    if not por_periodo and not (inicio and fim):
        return []

    # Preenche os períodos sem consulta com zero: um mês vazio também é informação
    primeiro = _inicio_do_periodo(inicio, agrupar) if inicio else min(por_periodo)
    ultimo = _inicio_do_periodo(fim, agrupar) if fim else max(por_periodo)
    serie, atual = [], primeiro
    while atual <= ultimo and len(serie) < 400:
        linha = por_periodo.get(atual, {})
        serie.append({
            "periodo": atual.isoformat(),
            "rotulo": _rotulo(atual, agrupar),
            "realizadas": linha.get("realizadas", 0),
            "agendadas": linha.get("agendadas", 0),
            "canceladas": linha.get("canceladas", 0),
            "total": linha.get("total", 0),
        })
        atual = _proximo_periodo(atual, agrupar)
    return serie


# ----------------------------------------------------------------------
# 4. Distribuição por dia da semana (consultas não canceladas)
# ----------------------------------------------------------------------
def por_dia_semana(base):
    contagem = dict(
        base.exclude(status=CANCELADA)
        .annotate(dia=ExtractIsoWeekDay("data"))  # 1 = segunda ... 7 = domingo
        .values("dia")
        .annotate(total=Count("id"))
        .order_by("dia")
        .values_list("dia", "total")
    )
    return [{"dia": nome, "total": contagem.get(i, 0)} for i, nome in enumerate(DIAS_SEMANA, start=1)]


# ----------------------------------------------------------------------
# Tudo junto: usado pela view HTML e pela API
# ----------------------------------------------------------------------
def montar_dashboard(org, form, mostra_series=True):
    base = consultas_da_organizacao(org)
    inicio = fim = None
    agrupar = "mes"
    if form.is_valid():
        inicio, fim = form.cleaned_data["inicio"], form.cleaned_data["fim"]
        agrupar = form.cleaned_data["agrupar"]
        if inicio:
            base = base.filter(data__gte=inicio)
        if fim:
            base = base.filter(data__lte=fim)

    dados = {
        "periodo": {
            "inicio": inicio.isoformat() if inicio else None,
            "fim": fim.isoformat() if fim else None,
            "agrupar": agrupar,
        },
        "kpis": kpis(base),
        "ranking": ranking_profissionais(base),
        "por_dia_semana": por_dia_semana(base),
    }
    if mostra_series:
        dados["serie"] = serie_temporal(base, agrupar, inicio, fim)
    return dados
