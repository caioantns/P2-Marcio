from datetime import date, time, timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .models import Consulta, Disponibilidade, Organizacao, Paciente, Perfil, Profissional
from .validators import validar_cpf


def proxima(dia_semana):
    """Próxima data (a partir de amanhã) que cai no dia da semana pedido."""
    d = timezone.localdate() + timedelta(days=1)
    while d.weekday() != dia_semana:
        d += timedelta(days=1)
    return d


def usuario(nome, org, papel=Perfil.Papel.ADMIN):
    u = User.objects.create_user(nome, password="senha-de-teste")
    Perfil.objects.create(usuario=u, organizacao=org, papel=papel)
    return u


class BaseAgenda(TestCase):
    def setUp(self):
        self.org = Organizacao.objects.create(nome="Clínica A")
        self.user = usuario("ana", self.org)
        self.client.force_login(self.user)
        self.prof = Profissional.objects.create(
            organizacao=self.org,
            nome="Dra. Ana", especialidade="Clínica geral", registro="CRM 1/RJ", duracao_consulta=30
        )
        # Segunda-feira das 08:00 às 12:00
        Disponibilidade.objects.create(
            profissional=self.prof, dia_semana=0, hora_inicio=time(8), hora_fim=time(12)
        )
        self.pac = Paciente.objects.create(organizacao=self.org, nome="João", cpf="52998224725", telefone="21999999999")
        self.pac2 = Paciente.objects.create(organizacao=self.org, nome="Maria", cpf="11144477735", telefone="21988888888")
        self.segunda = proxima(0)

    def nova(self, **kw):
        dados = {"paciente": self.pac, "profissional": self.prof, "data": self.segunda, "hora_inicio": time(9)}
        dados.update(kw)
        return Consulta(**dados)


class RegrasConsultaTests(BaseAgenda):
    def test_agenda_dentro_da_disponibilidade_e_calcula_fim(self):
        c = self.nova()
        c.save()
        self.assertEqual(c.hora_fim, time(9, 30))
        self.assertEqual(c.status, Consulta.Status.AGENDADA)

    def test_bloqueia_dia_sem_atendimento(self):
        with self.assertRaisesMessage(ValidationError, "não atende"):
            self.nova(data=proxima(1)).save()  # terça

    def test_bloqueia_horario_fora_da_faixa(self):
        with self.assertRaisesMessage(ValidationError, "Fora da disponibilidade"):
            self.nova(hora_inicio=time(13)).save()

    def test_bloqueia_consulta_que_ultrapassa_o_fim_da_faixa(self):
        with self.assertRaisesMessage(ValidationError, "Fora da disponibilidade"):
            self.nova(hora_inicio=time(11, 45)).save()  # terminaria 12:15

    def test_bloqueia_sobreposicao_do_profissional(self):
        self.nova().save()
        with self.assertRaisesMessage(ValidationError, "já tem consulta"):
            self.nova(paciente=self.pac2, hora_inicio=time(9, 15)).save()

    def test_permite_horario_encostado(self):
        self.nova().save()
        self.nova(paciente=self.pac2, hora_inicio=time(9, 30)).save()
        self.assertEqual(Consulta.objects.count(), 2)

    def test_consulta_cancelada_libera_o_horario(self):
        c = self.nova()
        c.save()
        c.status = Consulta.Status.CANCELADA
        c.save()
        self.nova(paciente=self.pac2).save()
        self.assertEqual(Consulta.objects.exclude(status="cancelada").count(), 1)

    def test_bloqueia_paciente_em_dois_lugares(self):
        outro = Profissional.objects.create(organizacao=self.org, nome="Dr. Beto", especialidade="Cardio", registro="CRM 2/RJ")
        Disponibilidade.objects.create(profissional=outro, dia_semana=0, hora_inicio=time(8), hora_fim=time(12))
        self.nova().save()
        with self.assertRaisesMessage(ValidationError, "paciente já tem"):
            self.nova(profissional=outro).save()

    def test_bloqueia_data_no_passado(self):
        passado = self.segunda - timedelta(days=14)  # uma segunda-feira que já passou
        with self.assertRaisesMessage(ValidationError, "já passou"):
            self.nova(data=passado).save()

    def test_bloqueia_profissional_inativo(self):
        self.prof.ativo = False
        self.prof.save()
        with self.assertRaisesMessage(ValidationError, "inativo"):
            self.nova().save()

    def test_editar_sem_mudar_horario_nao_revalida_passado(self):
        c = self.nova()
        c.save()
        # Simula a consulta ter ficado no passado e depois ser marcada como realizada
        Consulta.objects.filter(pk=c.pk).update(data=self.segunda - timedelta(days=14))
        c.refresh_from_db()
        c.status = Consulta.Status.REALIZADA
        c.save()
        self.assertEqual(Consulta.objects.get(pk=c.pk).status, "realizada")

    def test_horarios_livres(self):
        self.nova(hora_inicio=time(8)).save()
        livres = self.prof.horarios_livres(self.segunda)
        self.assertNotIn(time(8), livres)
        self.assertIn(time(8, 30), livres)
        self.assertEqual(len(livres), 7)  # 8 slots de 30 min na faixa, 1 ocupado


class DisponibilidadeTests(BaseAgenda):
    def test_fim_antes_do_inicio(self):
        with self.assertRaises(ValidationError):
            Disponibilidade.objects.create(profissional=self.prof, dia_semana=1, hora_inicio=time(10), hora_fim=time(9))

    def test_faixas_sobrepostas(self):
        with self.assertRaisesMessage(ValidationError, "sobrepõe"):
            Disponibilidade.objects.create(profissional=self.prof, dia_semana=0, hora_inicio=time(11), hora_fim=time(14))


class CpfTests(TestCase):
    def test_cpf_valido(self):
        validar_cpf("52998224725")

    def test_cpf_invalido(self):
        for cpf in ("52998224724", "11111111111", "123"):
            with self.assertRaises(ValidationError):
                validar_cpf(cpf)


class ViewsTests(BaseAgenda):
    def test_paginas_abrem(self):
        c = self.nova()
        c.save()
        urls = [
            reverse("agenda_dia"), f"{reverse('agenda_dia')}?data={self.segunda:%Y-%m-%d}",
            reverse("consulta_lista"), reverse("consulta_nova"), c.get_absolute_url(),
            reverse("consulta_editar", args=[c.pk]),
            reverse("paciente_lista"), self.pac.get_absolute_url(), reverse("paciente_novo"),
            reverse("profissional_lista"), self.prof.get_absolute_url(), reverse("profissional_novo"),
            reverse("disponibilidade_nova") + f"?profissional={self.prof.pk}",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_formulario_mostra_erro_de_conflito(self):
        self.nova().save()
        resp = self.client.post(reverse("consulta_nova"), {
            "paciente": self.pac2.pk, "profissional": self.prof.pk,
            "data": f"{self.segunda:%Y-%m-%d}", "hora_inicio": "09:10",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "já tem consulta")

    def test_formulario_agenda_com_sucesso(self):
        resp = self.client.post(reverse("consulta_nova"), {
            "paciente": self.pac.pk, "profissional": self.prof.pk,
            "data": f"{self.segunda:%Y-%m-%d}", "hora_inicio": "10:00",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Consulta.objects.get().hora_fim, time(10, 30))

    def test_nao_exclui_paciente_com_consulta(self):
        self.nova().save()
        self.client.post(reverse("paciente_excluir", args=[self.pac.pk]))
        self.assertTrue(Paciente.objects.filter(pk=self.pac.pk).exists())

    def test_cadastro_paciente_limpa_pontuacao_do_cpf(self):
        self.client.post(reverse("paciente_novo"), {"nome": "Teste", "cpf": "390.533.447-05", "telefone": "21"})
        self.assertTrue(Paciente.objects.filter(cpf="39053344705").exists())


# ======================================================================
# P2 — Login, organização e papéis
# ======================================================================
class AcessoTests(BaseAgenda):
    def setUp(self):
        super().setUp()
        self.org_b = Organizacao.objects.create(nome="Clínica B")
        self.bruno = usuario("bruno", self.org_b)
        self.carla = usuario("carla", self.org, Perfil.Papel.OPERADOR)

    def test_sem_login_vai_para_a_tela_de_entrar(self):
        self.client.logout()
        resp = self.client.get(reverse("consulta_lista"))
        self.assertRedirects(resp, f"{reverse('login')}?next={reverse('consulta_lista')}")

    def test_usuario_sem_organizacao_recebe_403(self):
        User.objects.create_user("solto", password="x")
        self.client.login(username="solto", password="x")
        self.assertEqual(self.client.get(reverse("agenda_dia")).status_code, 403)

    def test_outra_organizacao_nao_ve_os_registros(self):
        self.client.force_login(self.bruno)
        self.assertEqual(self.client.get(self.pac.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(self.prof.get_absolute_url()).status_code, 404)
        self.assertNotContains(self.client.get(reverse("paciente_lista")), "João")

    def test_selects_do_formulario_so_listam_a_propria_organizacao(self):
        Paciente.objects.create(organizacao=self.org_b, nome="Paciente da B", cpf="39053344705", telefone="1")
        resp = self.client.get(reverse("consulta_nova"))
        self.assertContains(resp, "João")
        self.assertNotContains(resp, "Paciente da B")

    def test_nao_agenda_paciente_de_outra_organizacao(self):
        de_fora = Paciente.objects.create(organizacao=self.org_b, nome="Externo", cpf="39053344705", telefone="1")
        with self.assertRaisesMessage(ValidationError, "organizações diferentes"):
            self.nova(paciente=de_fora).save()

    def test_mesmo_cpf_pode_existir_em_clinicas_diferentes(self):
        Paciente.objects.create(organizacao=self.org_b, nome="João na B", cpf=self.pac.cpf, telefone="1")
        self.assertEqual(Paciente.objects.filter(cpf=self.pac.cpf).count(), 2)

    def test_cpf_repetido_na_mesma_clinica_mostra_erro(self):
        resp = self.client.post(reverse("paciente_novo"), {"nome": "Outro", "cpf": "529.982.247-25", "telefone": "1"})
        self.assertContains(resp, "Já existe um paciente com esse CPF")

    def test_operador_agenda_mas_nao_gerencia_profissionais_nem_exclui(self):
        self.client.force_login(self.carla)
        self.assertEqual(self.client.get(reverse("consulta_nova")).status_code, 200)
        self.assertEqual(self.client.get(reverse("profissional_novo")).status_code, 403)
        self.assertEqual(self.client.post(reverse("paciente_excluir", args=[self.pac2.pk])).status_code, 403)
        self.assertTrue(Paciente.objects.filter(pk=self.pac2.pk).exists())

    def test_superusuario_sem_perfil_ganha_perfil_de_admin(self):
        su = User.objects.create_superuser("root", password="x")
        self.client.force_login(su)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertTrue(Perfil.objects.get(usuario=su).eh_admin)


# ======================================================================
# P2 — Dashboard e relatórios (Aula 17)
# Dados conhecidos, fáceis de conferir à mão: clínica A tem 3 consultas, clínica B tem 5.
# ======================================================================
def segunda_feira(ano, mes, semana=0):
    d = date(ano, mes, 1)
    while d.weekday() != 0:
        d += timedelta(days=1)
    return d + timedelta(weeks=semana)


class BaseDashboard(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organizacao.objects.create(nome="Clínica A")
        cls.org_b = Organizacao.objects.create(nome="Clínica B")
        cls.ana = usuario("ana", cls.org_a)
        cls.carla = usuario("carla", cls.org_a, Perfil.Papel.OPERADOR)
        cls.bruno = usuario("bruno", cls.org_b)

        def montar(org, sufixo):
            prof = Profissional.objects.create(
                organizacao=org, nome=f"Dra. {sufixo}", especialidade="Clínica", registro=f"CRM {sufixo}"
            )
            Disponibilidade.objects.create(profissional=prof, dia_semana=0, hora_inicio=time(8), hora_fim=time(18))
            pac = Paciente.objects.create(organizacao=org, nome=f"Paciente {sufixo}", cpf="52998224725", telefone="1")
            return prof, pac

        cls.prof_a, cls.pac_a = montar(cls.org_a, "A")
        cls.prof_b, cls.pac_b = montar(cls.org_b, "B")
        R, C = Consulta.Status.REALIZADA, Consulta.Status.CANCELADA

        # Clínica A: agosto 2 (1 realizada, 1 cancelada) + setembro 1 realizada = 3
        for dia, hora, status in [
            (segunda_feira(2025, 8), time(8), R),
            (segunda_feira(2025, 8, 1), time(9), C),
            (segunda_feira(2025, 9), time(10), R),
        ]:
            Consulta.objects.create(paciente=cls.pac_a, profissional=cls.prof_a, data=dia, hora_inicio=hora, status=status)
        # Clínica B: 5 realizadas em outubro
        for i in range(5):
            Consulta.objects.create(
                paciente=cls.pac_b, profissional=cls.prof_b, data=segunda_feira(2025, 10),
                hora_inicio=time(8 + i), status=R,
            )

    def setUp(self):
        self.client.force_login(self.ana)

    def get(self, **params):
        return self.client.get(reverse("dashboard"), params)


class DashboardTests(BaseDashboard):

    def test_total_so_da_organizacao(self):
        self.assertEqual(self.get().context["kpis"]["total"], 3)
        self.client.force_login(self.bruno)
        self.assertEqual(self.get().context["kpis"]["total"], 5)

    def test_kpis_por_status(self):
        k = self.get().context["kpis"]
        self.assertEqual((k["realizadas"], k["canceladas"], k["agendadas"]), (2, 1, 0))
        self.assertEqual(k["taxa_cancelamento"], 33.3)
        self.assertEqual(k["pacientes"], 1)

    def test_periodo_filtra_todas_as_metricas(self):
        r = self.get(inicio="2025-09-01", fim="2025-09-30")
        self.assertEqual(r.context["kpis"]["total"], 1)
        self.assertEqual(r.context["ranking"][0]["total"], 1)
        self.assertEqual([p["total"] for p in r.context["serie"]], [1])

    def test_serie_por_mes_em_ordem_e_soma_igual_ao_cartao(self):
        r = self.get()
        serie = r.context["serie"]
        self.assertEqual([p["rotulo"] for p in serie], ["ago/2025", "set/2025"])
        self.assertEqual([p["total"] for p in serie], [2, 1])
        self.assertEqual(r.context["soma_serie"], r.context["kpis"]["total"])

    def test_serie_preenche_meses_vazios_com_zero(self):
        r = self.get(inicio="2025-07-01", fim="2025-10-31")
        self.assertEqual([p["total"] for p in r.context["serie"]], [0, 2, 1, 0])

    def test_serie_por_semana(self):
        r = self.get(inicio="2025-08-01", fim="2025-08-31", agrupar="semana")
        self.assertEqual(sum(p["total"] for p in r.context["serie"]), 2)

    def test_ranking_e_dia_da_semana(self):
        r = self.get()
        self.assertEqual(r.context["ranking"][0]["profissional__nome"], "Dra. A")
        segunda = r.context["por_dia_semana"][0]
        self.assertEqual(segunda, {"dia": "Seg", "total": 2})  # a cancelada não entra

    def test_data_invalida_na_url_nao_gera_erro_500(self):
        r = self.get(inicio="abc", fim="2025-13-40")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["form"].errors)
        self.assertEqual(r.context["kpis"]["total"], 3)  # filtro ignorado

    def test_inicio_depois_do_fim_mostra_erro(self):
        r = self.get(inicio="2025-09-30", fim="2025-09-01")
        self.assertContains(r, "A data inicial precisa ser antes da final")

    def test_dashboard_vazio_sem_erro(self):
        r = self.get(inicio="2030-01-01", fim="2030-01-31")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["kpis"]["total"], 0)
        self.assertContains(r, "Sem dados no período")

    def test_operador_nao_ve_series_nem_exporta(self):
        self.client.force_login(self.carla)
        r = self.get()
        self.assertFalse(r.context["mostra_series"])
        self.assertNotIn("serie", r.context)
        self.assertNotContains(r, "Exportar CSV")
        self.assertEqual(self.client.get(reverse("dashboard_csv")).status_code, 403)

    def test_numero_de_consultas_nao_cresce_com_os_dados(self):
        """Trava o desempenho: sem N+1, 3 ou 30 consultas geram o mesmo número de queries."""
        with CaptureQueriesContext(connection) as antes:
            self.get()
        for i in range(27):
            Consulta.objects.create(
                paciente=self.pac_a, profissional=self.prof_a, data=segunda_feira(2025, 6, i % 4),
                hora_inicio=time(8 + i // 4), status=Consulta.Status.REALIZADA,
            )
        with self.assertNumQueries(len(antes)):
            self.get()


class ExportacaoEApiTests(BaseDashboard):

    def test_csv_usa_a_mesma_base_filtrada(self):
        r = self.client.get(reverse("dashboard_csv"), {"inicio": "2025-08-01", "fim": "2025-08-31"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("consultas_de_2025-08-01_ate_2025-08-31.csv", r["Content-Disposition"])
        linhas = r.content.decode("utf-8-sig").strip().splitlines()
        self.assertEqual(len(linhas), 1 + 2)  # cabeçalho + 2 consultas de agosto
        self.assertTrue(linhas[0].startswith("Data;Início;Fim;Paciente"))
        self.assertNotIn("Paciente B", r.content.decode())

    def test_csv_neutraliza_formula_do_excel(self):
        Paciente.objects.filter(pk=self.pac_a.pk).update(nome='=HYPERLINK("http://mal.com")')
        r = self.client.get(reverse("dashboard_csv"))
        self.assertIn("'=HYPERLINK", r.content.decode())

    def test_csv_sem_n_mais_1(self):
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("dashboard_csv"))
        consultas_sql = [q for q in ctx.captured_queries if "agenda_paciente" in q["sql"]]
        self.assertEqual(len(consultas_sql), 1)  # paciente e profissional vêm no mesmo JOIN

    def test_api_do_dashboard(self):
        r = self.client.get(reverse("api_dashboard"), {"inicio": "2025-09-01"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["kpis"]["total"], 1)
        self.assertEqual(r.json()["organizacao"], "Clínica A")

    def test_api_isola_organizacao_e_valida_data(self):
        self.client.force_login(self.bruno)
        self.assertEqual(self.client.get(reverse("api_dashboard")).json()["kpis"]["total"], 5)
        self.assertEqual(self.client.get(reverse("api_dashboard"), {"fim": "xx"}).status_code, 400)

    def test_api_exige_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("api_dashboard")).status_code, 403)


class ConsultasSqlTests(BaseAgenda):
    """Método 7 da aula: assertNumQueries trava o N+1."""

    def test_listagem_com_select_related_faz_uma_consulta(self):
        for h in (8, 9, 10):
            self.nova(hora_inicio=time(h)).save()
        with self.assertNumQueries(1):
            for c in Consulta.objects.select_related("paciente", "profissional"):
                (c.paciente.nome, c.profissional.nome)
