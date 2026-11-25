from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from .validators import validar_cpf


# ----------------------------------------------------------------------
# Organização e perfil (multi-tenant): cada clínica só enxerga os próprios dados
# ----------------------------------------------------------------------
class Organizacao(models.Model):
    nome = models.CharField("nome", max_length=150)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "organização"
        verbose_name_plural = "organizações"

    def __str__(self):
        return self.nome


class Perfil(models.Model):
    class Papel(models.TextChoices):
        ADMIN = "admin", "Administrador"
        OPERADOR = "operador", "Operador (recepção)"

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil"
    )
    organizacao = models.ForeignKey(
        Organizacao, on_delete=models.PROTECT, related_name="perfis", verbose_name="organização"
    )
    papel = models.CharField("papel", max_length=10, choices=Papel.choices, default=Papel.OPERADOR)

    class Meta:
        verbose_name = "perfil"
        verbose_name_plural = "perfis"

    def __str__(self):
        return f"{self.usuario} · {self.organizacao} ({self.get_papel_display()})"

    @property
    def eh_admin(self):
        return self.papel == self.Papel.ADMIN


class Paciente(models.Model):
    organizacao = models.ForeignKey(
        Organizacao, on_delete=models.PROTECT, related_name="pacientes", verbose_name="organização"
    )
    nome = models.CharField("nome completo", max_length=150)
    cpf = models.CharField("CPF", max_length=11, validators=[validar_cpf])
    telefone = models.CharField("telefone", max_length=20)
    email = models.EmailField("e-mail", blank=True)
    data_nascimento = models.DateField("data de nascimento", null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "paciente"
        verbose_name_plural = "pacientes"
        constraints = [
            # O mesmo CPF pode existir em clínicas diferentes, mas não duas vezes na mesma
            models.UniqueConstraint(fields=["organizacao", "cpf"], name="cpf_unico_por_organizacao"),
        ]

    def __str__(self):
        return self.nome

    def get_absolute_url(self):
        return reverse("paciente_detalhe", args=[self.pk])

    @property
    def cpf_formatado(self):
        c = self.cpf
        return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}" if len(c) == 11 else c


class Profissional(models.Model):
    organizacao = models.ForeignKey(
        Organizacao, on_delete=models.PROTECT, related_name="profissionais", verbose_name="organização"
    )
    nome = models.CharField("nome", max_length=150)
    especialidade = models.CharField("especialidade", max_length=100)
    registro = models.CharField(
        "registro profissional", max_length=30,
        help_text="Ex.: CRM 12345/RJ, CRP 05/12345",
    )
    duracao_consulta = models.PositiveSmallIntegerField(
        "duração padrão da consulta (min)", default=30,
        help_text="Usada para calcular o fim da consulta quando ele não é informado.",
    )
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "profissional"
        verbose_name_plural = "profissionais"
        constraints = [
            models.UniqueConstraint(
                fields=["organizacao", "registro"], name="registro_unico_por_organizacao"
            ),
        ]

    def __str__(self):
        return f"{self.nome} ({self.especialidade})"

    def get_absolute_url(self):
        return reverse("profissional_detalhe", args=[self.pk])

    def clean(self):
        if self.duracao_consulta is not None and not 5 <= self.duracao_consulta <= 240:
            raise ValidationError({"duracao_consulta": "Use uma duração entre 5 e 240 minutos."})

    def horarios_livres(self, data):
        """
        Lista os horários de início livres numa data, em passos da duração padrão.
        Considera as disponibilidades do dia da semana e ignora consultas canceladas.
        """
        passo = timedelta(minutes=self.duracao_consulta)
        ocupadas = list(
            self.consultas.filter(data=data)
            .exclude(status=Consulta.Status.CANCELADA)
            .values_list("hora_inicio", "hora_fim")
        )
        agora = timezone.localtime()
        livres = []
        for disp in self.disponibilidades.filter(dia_semana=data.weekday()):
            inicio = datetime.combine(data, disp.hora_inicio)
            limite = datetime.combine(data, disp.hora_fim)
            while inicio + passo <= limite:
                fim = inicio + passo
                conflita = any(
                    o_ini < fim.time() and o_fim > inicio.time() for o_ini, o_fim in ocupadas
                )
                no_passado = data < agora.date() or (
                    data == agora.date() and inicio.time() <= agora.time()
                )
                if not conflita and not no_passado:
                    livres.append(inicio.time())
                inicio = fim
        return sorted(livres)


class Disponibilidade(models.Model):
    class DiaSemana(models.IntegerChoices):
        # Mesma numeração do date.weekday() do Python (segunda = 0)
        SEGUNDA = 0, "Segunda-feira"
        TERCA = 1, "Terça-feira"
        QUARTA = 2, "Quarta-feira"
        QUINTA = 3, "Quinta-feira"
        SEXTA = 4, "Sexta-feira"
        SABADO = 5, "Sábado"
        DOMINGO = 6, "Domingo"

    profissional = models.ForeignKey(
        Profissional, on_delete=models.CASCADE, related_name="disponibilidades"
    )
    dia_semana = models.IntegerField("dia da semana", choices=DiaSemana.choices)
    hora_inicio = models.TimeField("início")
    hora_fim = models.TimeField("fim")

    class Meta:
        ordering = ["profissional__nome", "dia_semana", "hora_inicio"]
        verbose_name = "disponibilidade"
        verbose_name_plural = "disponibilidades"

    def __str__(self):
        return (
            f"{self.profissional.nome} - {self.get_dia_semana_display()} "
            f"{self.hora_inicio:%H:%M}–{self.hora_fim:%H:%M}"
        )

    def clean(self):
        if not (self.hora_inicio and self.hora_fim):
            return
        if self.hora_fim <= self.hora_inicio:
            raise ValidationError({"hora_fim": "O fim precisa ser depois do início."})

        if self.profissional_id is not None and self.dia_semana is not None:
            sobreposta = (
                Disponibilidade.objects.filter(
                    profissional_id=self.profissional_id,
                    dia_semana=self.dia_semana,
                    hora_inicio__lt=self.hora_fim,
                    hora_fim__gt=self.hora_inicio,
                )
                .exclude(pk=self.pk)
                .first()
            )
            if sobreposta:
                raise ValidationError(
                    f"Esse horário se sobrepõe a outra disponibilidade já cadastrada "
                    f"({sobreposta.hora_inicio:%H:%M}–{sobreposta.hora_fim:%H:%M})."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class Consulta(models.Model):
    class Status(models.TextChoices):
        AGENDADA = "agendada", "Agendada"
        REALIZADA = "realizada", "Realizada"
        CANCELADA = "cancelada", "Cancelada"

    paciente = models.ForeignKey(Paciente, on_delete=models.PROTECT, related_name="consultas")
    profissional = models.ForeignKey(
        Profissional, on_delete=models.PROTECT, related_name="consultas"
    )
    data = models.DateField("data")
    hora_inicio = models.TimeField("início")
    hora_fim = models.TimeField(
        "fim", blank=True,
        help_text="Deixe em branco para usar a duração padrão do profissional.",
    )
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.AGENDADA
    )
    observacoes = models.TextField("observações", blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["data", "hora_inicio"]
        verbose_name = "consulta"
        verbose_name_plural = "consultas"
        # Campos usados em filter, order_by e agrupamentos do dashboard e da agenda
        indexes = [
            models.Index(fields=["data"], name="consulta_data_idx"),
            models.Index(fields=["profissional", "data"], name="consulta_prof_data_idx"),
            models.Index(fields=["status"], name="consulta_status_idx"),
        ]

    def __str__(self):
        return (
            f"{self.paciente} com {self.profissional.nome} "
            f"em {self.data:%d/%m/%Y} {self.hora_inicio:%H:%M}"
        )

    def get_absolute_url(self):
        return reverse("consulta_detalhe", args=[self.pk])

    # ------------------------------------------------------------------
    # Regra de negócio do P1: agendamento dentro da disponibilidade real
    # ------------------------------------------------------------------
    def clean(self):
        # Os campos obrigatórios já têm erro próprio; sem eles não dá para validar a agenda.
        if not (self.data and self.hora_inicio and self.profissional_id):
            return

        profissional = Profissional.objects.get(pk=self.profissional_id)

        # Paciente e profissional precisam ser da mesma organização (isolamento entre clínicas)
        if self.paciente_id:
            org_paciente = (
                Paciente.objects.filter(pk=self.paciente_id)
                .values_list("organizacao_id", flat=True).first()
            )
            if org_paciente != profissional.organizacao_id:
                raise ValidationError("Paciente e profissional pertencem a organizações diferentes.")

        # 1. Calcula o fim automaticamente pela duração padrão do profissional
        if not self.hora_fim:
            fim = datetime.combine(self.data, self.hora_inicio) + timedelta(
                minutes=profissional.duracao_consulta
            )
            if fim.date() != self.data:
                raise ValidationError({"hora_inicio": "A consulta não pode passar da meia-noite."})
            self.hora_fim = fim.time()

        if self.hora_fim <= self.hora_inicio:
            raise ValidationError({"hora_fim": "O fim precisa ser depois do início."})

        # Consultas canceladas não ocupam a agenda, então dispensam as checagens abaixo
        if self.status == self.Status.CANCELADA:
            return

        erros = []
        horario_mudou = self._horario_mudou()

        # 2. Não permite agendar no passado
        if self.status == self.Status.AGENDADA and horario_mudou:
            inicio = timezone.make_aware(datetime.combine(self.data, self.hora_inicio))
            if inicio <= timezone.now():
                erros.append("Não é possível agendar em uma data ou horário que já passou.")

        # 3. Profissional precisa estar ativo para receber novos horários
        if not profissional.ativo and horario_mudou:
            erros.append(f"{profissional.nome} está inativo e não recebe novos agendamentos.")

        # 4. O horário inteiro precisa caber numa disponibilidade daquele dia da semana
        cabe = profissional.disponibilidades.filter(
            dia_semana=self.data.weekday(),
            hora_inicio__lte=self.hora_inicio,
            hora_fim__gte=self.hora_fim,
        ).exists()
        if not cabe:
            dia = Disponibilidade.DiaSemana(self.data.weekday()).label.lower()
            faixas = profissional.disponibilidades.filter(dia_semana=self.data.weekday())
            if faixas:
                texto = ", ".join(f"{f.hora_inicio:%H:%M}–{f.hora_fim:%H:%M}" for f in faixas)
                erros.append(f"Fora da disponibilidade de {profissional.nome} na {dia} ({texto}).")
            else:
                erros.append(f"{profissional.nome} não atende na {dia}.")

        # 5. Sem sobreposição com outra consulta do mesmo profissional
        #    (dois intervalos se sobrepõem quando início A < fim B e fim A > início B)
        ativas = (
            Consulta.objects.filter(
                data=self.data,
                hora_inicio__lt=self.hora_fim,
                hora_fim__gt=self.hora_inicio,
            )
            .exclude(status=self.Status.CANCELADA)
            .exclude(pk=self.pk)
        )
        conflito = ativas.filter(profissional_id=self.profissional_id).first()
        if conflito:
            erros.append(
                f"{profissional.nome} já tem consulta das "
                f"{conflito.hora_inicio:%H:%M} às {conflito.hora_fim:%H:%M} nesse dia."
            )

        # 6. O paciente também não pode estar em duas consultas ao mesmo tempo
        if self.paciente_id:
            conflito_paciente = ativas.filter(paciente_id=self.paciente_id).first()
            if conflito_paciente:
                erros.append(
                    "O paciente já tem outra consulta das "
                    f"{conflito_paciente.hora_inicio:%H:%M} às "
                    f"{conflito_paciente.hora_fim:%H:%M} nesse dia."
                )

        if erros:
            raise ValidationError(erros)

    def _horario_mudou(self):
        """True para consulta nova ou quando data, horário ou profissional foram alterados."""
        if self.pk is None:
            return True
        antiga = (
            Consulta.objects.filter(pk=self.pk)
            .values("data", "hora_inicio", "hora_fim", "profissional_id")
            .first()
        )
        if antiga is None:
            return True
        return (
            antiga["data"] != self.data
            or antiga["hora_inicio"] != self.hora_inicio
            or antiga["hora_fim"] != self.hora_fim
            or antiga["profissional_id"] != self.profissional_id
        )

    def save(self, *args, **kwargs):
        # Garante a regra mesmo quando a consulta é criada pelo shell ou por outro código
        self.full_clean()
        super().save(*args, **kwargs)
