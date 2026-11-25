from django import forms

from .models import Consulta, Disponibilidade, Paciente, Profissional

DATA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
HORA = forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


class OrganizacaoFormMixin:
    """Recebe a organização do usuário e limita os selects a ela."""

    def __init__(self, *args, organizacao=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organizacao = organizacao
        if organizacao is not None:
            for nome, model in (("paciente", Paciente), ("profissional", Profissional)):
                if nome in self.fields:
                    self.fields[nome].queryset = self.fields[nome].queryset.filter(organizacao=organizacao)


class PacienteForm(OrganizacaoFormMixin, forms.ModelForm):
    # 14 caracteres para aceitar o CPF digitado com pontuação (000.000.000-00)
    cpf = forms.CharField(label="CPF", max_length=14)

    class Meta:
        model = Paciente
        fields = ["nome", "cpf", "telefone", "email", "data_nascimento"]
        widgets = {
            "data_nascimento": DATA,
            "telefone": forms.TextInput(attrs={"placeholder": "(21) 99999-9999"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cpf"].widget.attrs.update({"placeholder": "000.000.000-00", "inputmode": "numeric"})

    def clean_cpf(self):
        # Aceita com ou sem pontuação e salva só os números
        cpf = "".join(c for c in self.cleaned_data["cpf"] if c.isdigit())
        repetido = Paciente.objects.filter(
            organizacao_id=self.instance.organizacao_id, cpf=cpf
        ).exclude(pk=self.instance.pk)
        if repetido.exists():
            raise forms.ValidationError("Já existe um paciente com esse CPF.")
        return cpf


class ProfissionalForm(OrganizacaoFormMixin, forms.ModelForm):
    class Meta:
        model = Profissional
        fields = ["nome", "especialidade", "registro", "duracao_consulta", "ativo"]

    def clean_registro(self):
        registro = self.cleaned_data["registro"].strip()
        repetido = Profissional.objects.filter(
            organizacao_id=self.instance.organizacao_id, registro=registro
        ).exclude(pk=self.instance.pk)
        if repetido.exists():
            raise forms.ValidationError("Já existe um profissional com esse registro.")
        return registro


class DisponibilidadeForm(OrganizacaoFormMixin, forms.ModelForm):
    class Meta:
        model = Disponibilidade
        fields = ["profissional", "dia_semana", "hora_inicio", "hora_fim"]
        widgets = {"hora_inicio": HORA, "hora_fim": HORA}


class ConsultaForm(OrganizacaoFormMixin, forms.ModelForm):
    class Meta:
        model = Consulta
        fields = ["paciente", "profissional", "data", "hora_inicio", "hora_fim", "status", "observacoes"]
        widgets = {
            "data": DATA,
            "hora_inicio": HORA,
            "hora_fim": HORA,
            "observacoes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Na criação, só lista profissionais ativos e esconde o status (nasce "agendada")
        if not self.instance.pk:
            self.fields["profissional"].queryset = self.fields["profissional"].queryset.filter(ativo=True)
            del self.fields["status"]


class FiltroConsultaForm(OrganizacaoFormMixin, forms.Form):
    data = forms.DateField(required=False, widget=DATA)
    profissional = forms.ModelChoiceField(
        queryset=Profissional.objects.all(), required=False, empty_label="Todos os profissionais"
    )
    status = forms.ChoiceField(
        choices=[("", "Todos os status")] + list(Consulta.Status.choices), required=False
    )


# ----------------------------------------------------------------------
# P2 — Dashboard: filtro por período validado
# ----------------------------------------------------------------------
class PeriodoForm(forms.Form):
    """
    Nunca confie na data digitada na URL: "abc" em ?inicio= quebraria o filtro com erro 500.
    O DateField valida e converte; se algo vier inválido, o dashboard ignora o filtro e
    mostra o erro no formulário.
    """

    AGRUPAMENTOS = [("mes", "Por mês"), ("semana", "Por semana"), ("dia", "Por dia")]

    inicio = forms.DateField(label="De", required=False, widget=DATA)
    fim = forms.DateField(label="Até", required=False, widget=DATA)
    agrupar = forms.ChoiceField(label="Agrupar", choices=AGRUPAMENTOS, required=False)

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("inicio"), dados.get("fim")
        if inicio and fim and inicio > fim:
            raise forms.ValidationError("A data inicial precisa ser antes da final.")
        if not dados.get("agrupar"):
            dados["agrupar"] = "mes"
        return dados
