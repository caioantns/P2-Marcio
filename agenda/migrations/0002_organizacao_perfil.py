"""
P2 — Organização e perfis.

Cria Organizacao e Perfil e liga pacientes e profissionais a uma organização.
Os registros que já existiam (do P1) vão para uma organização padrão,
"Clínica Principal", para nenhum dado ficar órfão.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def vincular_a_organizacao_padrao(apps, schema_editor):
    Organizacao = apps.get_model("agenda", "Organizacao")
    Paciente = apps.get_model("agenda", "Paciente")
    Profissional = apps.get_model("agenda", "Profissional")
    if not (Paciente.objects.exists() or Profissional.objects.exists()):
        return
    org, _ = Organizacao.objects.get_or_create(nome="Clínica Principal")
    Paciente.objects.filter(organizacao__isnull=True).update(organizacao=org)
    Profissional.objects.filter(organizacao__isnull=True).update(organizacao=org)


class Migration(migrations.Migration):

    dependencies = [
        ("agenda", "0001_inicial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Organizacao",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=150, verbose_name="nome")),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "organização",
                "verbose_name_plural": "organizações",
                "ordering": ["nome"],
            },
        ),
        migrations.CreateModel(
            name="Perfil",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("papel", models.CharField(
                    choices=[("admin", "Administrador"), ("operador", "Operador (recepção)")],
                    default="operador", max_length=10, verbose_name="papel",
                )),
                ("organizacao", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name="perfis",
                    to="agenda.organizacao", verbose_name="organização",
                )),
                ("usuario", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE, related_name="perfil",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"verbose_name": "perfil", "verbose_name_plural": "perfis"},
        ),
        # Primeiro nulo, para conseguir preencher os registros antigos
        migrations.AddField(
            model_name="paciente",
            name="organizacao",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="pacientes",
                to="agenda.organizacao", verbose_name="organização",
            ),
        ),
        migrations.AddField(
            model_name="profissional",
            name="organizacao",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="profissionais",
                to="agenda.organizacao", verbose_name="organização",
            ),
        ),
        migrations.RunPython(vincular_a_organizacao_padrao, migrations.RunPython.noop),
    ]
