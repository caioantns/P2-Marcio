"""
P2 — Organização obrigatória, CPF/registro únicos por organização e índices do dashboard.

Fica separada da 0002 porque o PostgreSQL não deixa alterar a tabela na mesma
transação em que os dados foram atualizados ("pending trigger events").
"""
import django.db.models.deletion
from django.db import migrations, models

import agenda.validators


class Migration(migrations.Migration):

    dependencies = [
        ("agenda", "0002_organizacao_perfil"),
    ]

    operations = [
        migrations.AlterField(
            model_name="paciente",
            name="organizacao",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="pacientes",
                to="agenda.organizacao", verbose_name="organização",
            ),
        ),
        migrations.AlterField(
            model_name="profissional",
            name="organizacao",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="profissionais",
                to="agenda.organizacao", verbose_name="organização",
            ),
        ),
        migrations.AlterField(
            model_name="paciente",
            name="cpf",
            field=models.CharField(
                max_length=11, validators=[agenda.validators.validar_cpf], verbose_name="CPF"
            ),
        ),
        migrations.AlterField(
            model_name="profissional",
            name="registro",
            field=models.CharField(
                help_text="Ex.: CRM 12345/RJ, CRP 05/12345", max_length=30,
                verbose_name="registro profissional",
            ),
        ),
        migrations.AddConstraint(
            model_name="paciente",
            constraint=models.UniqueConstraint(fields=("organizacao", "cpf"), name="cpf_unico_por_organizacao"),
        ),
        migrations.AddConstraint(
            model_name="profissional",
            constraint=models.UniqueConstraint(
                fields=("organizacao", "registro"), name="registro_unico_por_organizacao"
            ),
        ),
        migrations.AddIndex(
            model_name="consulta",
            index=models.Index(fields=["data"], name="consulta_data_idx"),
        ),
        migrations.AddIndex(
            model_name="consulta",
            index=models.Index(fields=["profissional", "data"], name="consulta_prof_data_idx"),
        ),
        migrations.AddIndex(
            model_name="consulta",
            index=models.Index(fields=["status"], name="consulta_status_idx"),
        ),
    ]
