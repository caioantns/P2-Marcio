# Agenda de Consultas — P2

Sistema de agendamento de consultas que valida a disponibilidade real do profissional.
Projeto da disciplina Laboratório de Programação Full Stack (Django + PostgreSQL).

## Entidades

| Model | O que representa |
|---|---|
| `Paciente` | Nome, CPF (validado), telefone, e-mail, nascimento |
| `Profissional` | Nome, especialidade, registro, duração padrão da consulta, ativo |
| `Disponibilidade` | Faixa de atendimento semanal de um profissional (ex.: segunda 08:00–12:00) |
| `Consulta` | Paciente + profissional + data + horário + status (agendada / realizada / cancelada) |

## Regra de negócio do P1

Implementada em `Consulta.clean()` (`agenda/models.py`) e aplicada nos formulários, no Admin e no shell (o `save()` chama `full_clean()`):

1. Se o fim não for informado, é calculado pela duração padrão do profissional.
2. Não é possível agendar em data ou horário que já passou.
3. Profissional inativo não recebe novos agendamentos.
4. A consulta inteira precisa caber numa disponibilidade do dia da semana.
5. O profissional não pode ter duas consultas sobrepostas.
6. O paciente não pode estar em duas consultas ao mesmo tempo.

Consultas canceladas liberam o horário. As disponibilidades de um mesmo profissional também não podem se sobrepor.

Extras: agenda do dia em linha do tempo, horários livres por profissional (clique no horário para agendar), filtros e paginação, busca de pacientes e bloqueio de exclusão de quem tem consultas.

## P2 — Dashboard e relatórios (Aula 17)

Para o dashboard funcionar como o slide pede, esta versão também traz as bases da P2:

- **Login** (`/entrar/`) em todas as telas.
- **Organização e perfil**: cada usuário pertence a uma clínica (`Organizacao`) e tem um papel (`Perfil`: administrador ou operador). Toda listagem, formulário, métrica e exportação é filtrada pela organização do usuário. CPF e registro passam a ser únicos *por clínica*.
- **Papéis**: o operador (recepção) agenda consultas e cadastra pacientes; só o administrador gerencia profissionais e horários, exclui registros, vê as séries por período e exporta CSV.
- **Django REST Framework** para a API do dashboard.

### As 4 perguntas do dono da clínica

| Pergunta | Métrica | Como é feita (`agenda/dashboard.py`) | Na tela |
|---|---|---|---|
| Quantas consultas tivemos e quantas foram canceladas? | KPI | `aggregate` com `Count(..., filter=Q(...))` | cartões |
| Quais profissionais mais atendem? | Ranking | `values` + `annotate` + `order_by` + `[:5]` | tabela com barra |
| O movimento está crescendo? | Série no tempo | `TruncMonth` / `TruncWeek` / `TruncDay` + `order_by` | barras empilhadas (Chart.js) |
| Quais dias da semana são mais cheios? | Distribuição | `ExtractIsoWeekDay` | barras (Chart.js) |

- **Filtro por período validado**: `PeriodoForm` (`?inicio=2026-08-01&fim=2026-09-30&agrupar=semana`). Data inválida não quebra a página: o filtro é ignorado e o erro aparece no formulário.
- **Gráficos**: a view manda os dados, `json_script` escreve o JSON seguro na página e `static/js/dashboard.js` desenha com `static/js/chart.umd.js` (Chart.js 4, sem CDN).
- **Exportar CSV**: `/dashboard/exportar.csv` com a mesma base filtrada (organização + período), separador `;` e acentos certos no Excel, proteção contra fórmula (`=`, `+`, `-`, `@`). Só administrador.
- **API**: `GET /api/dashboard/?inicio=...&fim=...` devolve o mesmo dado em JSON, reaproveitando as funções do `dashboard.py`.
- **Desempenho**: `select_related`/`prefetch_related` nas telas com FK, `list_select_related` no Admin, índices em `Consulta` (`data`, `profissional+data`, `status`) e testes com `assertNumQueries` que falham se o N+1 voltar.

### Usuários de demonstração

`python manage.py popular_dados` cria duas clínicas com ~6 meses de histórico (senha de todos: `agenda123`):

| Usuário | Clínica | Papel |
|---|---|---|
| `ana` | Clínica Saúde Integral | Administrador |
| `carla` | Clínica Saúde Integral | Operador (recepção) |
| `bruno` | Consultório Bem-Estar | Administrador |

Entre como `ana` e depois como `bruno`: nenhum número de uma clínica aparece na outra. Use `python manage.py popular_dados --recriar` para apagar e gerar de novo.

O superusuário do `createsuperuser` ganha um perfil de administrador na primeira clínica no primeiro acesso. Os dados que já existiam do P1 vão para a clínica "Clínica Principal" na migração.

### Vendo as consultas SQL

- **Debug toolbar**: `pip install -r requirements-dev.txt`. Com `DEBUG=True` ela liga sozinha (desligue com `DEBUG_TOOLBAR=False` no `.env`).
- **Log de SQL no terminal**: `LOG_SQL=True` no `.env`.
- **No shell**: `print(qs.query)`, `qs.explain()` ou `CaptureQueriesContext`.

## Como rodar

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac

pip install -r requirements.txt   # ou requirements-dev.txt para ter a debug toolbar
copy .env.example .env         # Linux/Mac: cp .env.example .env
# edite o .env com a senha do seu PostgreSQL
```

Crie o banco no PostgreSQL (pgAdmin ou psql):

```sql
CREATE DATABASE agenda_consultas;
```

Depois:

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py popular_dados   # opcional: dados de exemplo para demonstração
python manage.py runserver
```

- Sistema: http://127.0.0.1:8000/ (entre com `ana` / `agenda123`)
- Dashboard: http://127.0.0.1:8000/dashboard/
- API do dashboard: http://127.0.0.1:8000/api/dashboard/
- Admin: http://127.0.0.1:8000/admin/ (cadastre organizações e o perfil de cada usuário)

## Testes

```bash
python manage.py test agenda
```

49 testes: regras do P1, isolamento entre clínicas, papéis, métricas do dashboard com números conhecidos (clínica A com 3 consultas, clínica B com 5), filtro de período, data inválida, CSV, API e `assertNumQueries` contra N+1.

## Estrutura

```
clinica/             configurações do projeto (settings, urls)
agenda/              app principal
  models.py          entidades, organização/perfil e regras de negócio
  validators.py      validação de CPF
  forms.py           ModelForms, filtro de consultas e PeriodoForm
  permissoes.py      login, organização e papel (mixins e decorator)
  dashboard.py       métricas do dashboard (usadas pela tela e pela API)
  views.py           CRUD, agenda do dia, dashboard e exportação CSV
  api_views.py       API do dashboard (DRF)
  urls.py
  admin.py
  tests.py           testes das regras e das telas
  management/commands/popular_dados.py
  templates/agenda/  telas do app
templates/base.html  layout base (+ registration/login.html e 403.html)
static/css/          estilos
static/js/           Chart.js e dashboard.js
```
