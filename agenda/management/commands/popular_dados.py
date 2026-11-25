"""
Dados de demonstração da P2.

Cria duas clínicas (para provar o isolamento entre organizações), três usuários com
papéis diferentes e cerca de seis meses de histórico de consultas, para o dashboard
ter o que mostrar. Os números são aleatórios, mas com semente fixa: rodar de novo
gera sempre o mesmo resultado.

    python manage.py popular_dados            # só cria se o banco estiver vazio
    python manage.py popular_dados --recriar  # apaga tudo e cria de novo
"""
import random
from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from agenda.models import Consulta, Disponibilidade, Organizacao, Paciente, Perfil, Profissional

SENHA = "agenda123"
MESES_DE_HISTORICO = 6

NOMES = [
    "Ana Beatriz Lima", "Carlos Eduardo Souza", "Fernanda Rocha", "Gustavo Almeida",
    "Juliana Martins", "Marcos Vinícius Reis", "Patrícia Gomes", "Rodrigo Teixeira",
    "Camila Ferreira", "Diego Nascimento", "Larissa Costa", "Thiago Barbosa",
    "Beatriz Carvalho", "Felipe Araújo", "Mariana Ribeiro", "Lucas Pereira",
    "Aline Monteiro", "Bruno Cardoso", "Renata Dias", "Vinícius Moreira",
    "Sofia Mendes", "Eduardo Pinto", "Isabela Correia", "Rafael Lopes",
    "Gabriela Freitas", "Pedro Henrique Castro", "Letícia Vieira", "André Santana",
    "Natália Cunha", "Leonardo Batista", "Priscila Ramos", "Matheus Farias",
]


def gerar_cpf(rnd):
    base = [rnd.randint(0, 9) for _ in range(9)]
    while len(set(base)) == 1:
        base = [rnd.randint(0, 9) for _ in range(9)]
    for tamanho in (9, 10):
        soma = sum(d * (tamanho + 1 - i) for i, d in enumerate(base))
        base.append((soma * 10) % 11 % 10)
    return "".join(map(str, base))


def horarios_da_faixa(dia, disp, minutos):
    inicio = datetime.combine(dia, disp.hora_inicio)
    limite = datetime.combine(dia, disp.hora_fim)
    passo = timedelta(minutes=minutos)
    while inicio + passo <= limite:
        yield inicio.time()
        inicio += passo


class Command(BaseCommand):
    help = "Cria clínicas, usuários, profissionais, pacientes e ~6 meses de consultas de exemplo."

    def add_arguments(self, parser):
        parser.add_argument("--recriar", action="store_true", help="Apaga os dados existentes antes de criar.")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["recriar"]:
            Consulta.objects.all().delete()
            Disponibilidade.objects.all().delete()
            Paciente.objects.all().delete()
            Profissional.objects.all().delete()
            Perfil.objects.all().delete()
            User.objects.filter(username__in=["ana", "carla", "bruno"]).delete()
            Organizacao.objects.all().delete()
        elif Profissional.objects.exists():
            self.stdout.write(self.style.WARNING(
                "Já existem dados cadastrados; nada foi criado. Use --recriar para apagar e criar de novo."
            ))
            return

        rnd = random.Random(2026)
        hoje = timezone.localdate()

        clinica = Organizacao.objects.create(nome="Clínica Saúde Integral")
        consultorio = Organizacao.objects.create(nome="Consultório Bem-Estar")

        for usuario, nome, org, papel in [
            ("ana", "Ana Souza", clinica, Perfil.Papel.ADMIN),
            ("carla", "Carla Mendes", clinica, Perfil.Papel.OPERADOR),
            ("bruno", "Bruno Lima", consultorio, Perfil.Papel.ADMIN),
        ]:
            primeiro, ultimo = nome.split()
            u = User.objects.create_user(usuario, password=SENHA, first_name=primeiro, last_name=ultimo)
            Perfil.objects.create(usuario=u, organizacao=org, papel=papel)

        # ------------------------------------------------------------------
        # Profissionais e horários de atendimento
        # ------------------------------------------------------------------
        def prof(org, nome, esp, reg, minutos, faixas):
            p = Profissional.objects.create(
                organizacao=org, nome=nome, especialidade=esp, registro=reg, duracao_consulta=minutos
            )
            for dia, ini, fim in faixas:
                Disponibilidade.objects.create(profissional=p, dia_semana=dia, hora_inicio=ini, hora_fim=fim)
            return p

        equipe_clinica = [
            prof(clinica, "Dra. Helena Duarte", "Clínica geral", "CRM 52.10234/RJ", 30,
                 [(d, time(8), time(12)) for d in range(5)] + [(d, time(14), time(18)) for d in (0, 2, 4)]),
            prof(clinica, "Dr. Rafael Moura", "Cardiologia", "CRM 52.20981/RJ", 40,
                 [(d, time(9), time(13)) for d in (1, 3)] + [(5, time(8), time(12))]),
            prof(clinica, "Luana Prado", "Psicologia", "CRP 05/41822", 50,
                 [(d, time(13), time(19)) for d in range(5)]),
            prof(clinica, "Dr. Otávio Nunes", "Dermatologia", "CRM 52.33017/RJ", 30,
                 [(d, time(8), time(12)) for d in (0, 3)]),
        ]
        equipe_consultorio = [
            prof(consultorio, "Dra. Marina Siqueira", "Nutrição", "CRN 4/19021", 45,
                 [(d, time(9), time(15)) for d in (0, 2, 4)]),
            prof(consultorio, "Paulo Henrique Lessa", "Fisioterapia", "CREFITO 2/88104", 50,
                 [(d, time(7), time(12)) for d in (1, 3)]),
        ]

        # ------------------------------------------------------------------
        # Pacientes
        # ------------------------------------------------------------------
        def pacientes(org, nomes):
            return [
                Paciente.objects.create(
                    organizacao=org, nome=n, cpf=gerar_cpf(rnd),
                    telefone=f"(21) 9{rnd.randint(7000, 9999)}-{rnd.randint(1000, 9999)}",
                )
                for n in nomes
            ]

        pac_clinica = pacientes(clinica, NOMES[:26])
        pac_consultorio = pacientes(consultorio, NOMES[20:])

        # ------------------------------------------------------------------
        # Consultas: histórico (realizadas/canceladas) + próximas duas semanas (agendadas)
        # ------------------------------------------------------------------
        inicio_historico = (hoje.replace(day=1) - timedelta(days=31 * (MESES_DE_HISTORICO - 1))).replace(day=1)
        agora = timezone.localtime()
        total = {clinica: 0, consultorio: 0}

        def agendar(org, equipe, lista_pacientes, ocupacao_base):
            dias = (hoje + timedelta(days=14) - inicio_historico).days
            for n in range(dias + 1):
                dia = inicio_historico + timedelta(days=n)
                # Movimento crescendo ao longo dos meses, para a série ter tendência
                progresso = n / max(dias, 1)
                ocupacao = ocupacao_base + 0.25 * progresso
                ocupados_paciente = {}  # paciente -> lista de (ini, fim) no dia
                for p in equipe:
                    for disp in p.disponibilidades.all():
                        if disp.dia_semana != dia.weekday():
                            continue
                        for hora in horarios_da_faixa(dia, disp, p.duracao_consulta):
                            if rnd.random() > ocupacao:
                                continue
                            fim = (datetime.combine(dia, hora) + timedelta(minutes=p.duracao_consulta)).time()
                            paciente = rnd.choice(lista_pacientes)
                            choque = any(i < fim and f > hora for i, f in ocupados_paciente.get(paciente.pk, []))
                            if choque:
                                continue
                            ja_passou = datetime.combine(dia, hora) < agora.replace(tzinfo=None)
                            if ja_passou:
                                status = Consulta.Status.CANCELADA if rnd.random() < 0.11 else Consulta.Status.REALIZADA
                            else:
                                status = Consulta.Status.CANCELADA if rnd.random() < 0.05 else Consulta.Status.AGENDADA
                            Consulta.objects.create(
                                paciente=paciente, profissional=p, data=dia, hora_inicio=hora, status=status
                            )
                            if status != Consulta.Status.CANCELADA:
                                ocupados_paciente.setdefault(paciente.pk, []).append((hora, fim))
                            total[org] += 1

        agendar(clinica, equipe_clinica, pac_clinica, ocupacao_base=0.35)
        agendar(consultorio, equipe_consultorio, pac_consultorio, ocupacao_base=0.25)

        self.stdout.write(self.style.SUCCESS(
            f"{clinica}: {len(equipe_clinica)} profissionais, {len(pac_clinica)} pacientes, {total[clinica]} consultas.\n"
            f"{consultorio}: {len(equipe_consultorio)} profissionais, {len(pac_consultorio)} pacientes, "
            f"{total[consultorio]} consultas.\n"
            f"Usuários (senha {SENHA}): ana = admin da {clinica}; carla = operadora da {clinica}; "
            f"bruno = admin do {consultorio}."
        ))
