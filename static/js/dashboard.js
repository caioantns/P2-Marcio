/*
 * Gráficos do dashboard (Aula 17).
 *
 * O Django continua sendo o dono dos dados: a view monta as métricas, o template
 * escreve o JSON com {{ dados|json_script:"dados-dashboard" }} e este arquivo só
 * lê esse JSON e desenha com o Chart.js.
 */
(function () {
  const fonte = document.getElementById("dados-dashboard");
  if (!fonte || typeof Chart === "undefined") return;
  const dados = JSON.parse(fonte.textContent);

  // Cores por status (validadas para daltonismo e contraste); iguais às bolinhas dos cartões
  const COR = {
    realizada: "#4A63C9",
    agendada: "#0E9A84",
    cancelada: "#C8553A",
    barra: "#1D5E5A",
    grade: "#E7ECEE",
    eixo: "#5A6A74",
    superficie: "#FFFFFF",
  };

  Chart.defaults.font.family = '"Figtree", system-ui, sans-serif';
  Chart.defaults.font.size = 13;
  Chart.defaults.color = COR.eixo;
  Chart.defaults.maintainAspectRatio = false;

  const numero = (v) => Number(v).toLocaleString("pt-BR");

  const tooltip = {
    backgroundColor: "#16242C",
    padding: 10,
    cornerRadius: 6,
    titleFont: { weight: "600" },
    boxPadding: 4,
    callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${numero(ctx.parsed.y)}` },
  };

  const eixos = (empilhado) => ({
    x: {
      stacked: empilhado,
      grid: { display: false },
      border: { color: COR.grade },
      ticks: { maxRotation: 0, autoSkipPadding: 12 },
    },
    y: {
      stacked: empilhado,
      beginAtZero: true,
      grid: { color: COR.grade },
      border: { display: false },
      ticks: { precision: 0, callback: numero },
    },
  });

  // ---------- Série no tempo: barras empilhadas por status ----------
  const canvasSerie = document.getElementById("grafico-serie");
  if (canvasSerie && dados.serie.length) {
    const barra = (rotulo, campo, cor) => ({
      label: rotulo,
      data: dados.serie.map((p) => p[campo]),
      backgroundColor: cor,
      borderColor: COR.superficie, // 2px de respiro entre os segmentos
      borderWidth: { top: 2 },
      borderSkipped: "bottom",
      maxBarThickness: 44,
    });
    new Chart(canvasSerie, {
      type: "bar",
      data: {
        labels: dados.serie.map((p) => p.rotulo),
        datasets: [
          barra("Realizadas", "realizadas", COR.realizada),
          barra("Agendadas", "agendadas", COR.agendada),
          barra("Canceladas", "canceladas", COR.cancelada),
        ],
      },
      options: {
        interaction: { mode: "index", intersect: false }, // passa o mouse na coluna toda
        plugins: {
          legend: { display: false }, // a legenda fica no HTML, acima do gráfico
          tooltip: {
            ...tooltip,
            callbacks: {
              ...tooltip.callbacks,
              footer: (itens) => `Total: ${numero(itens.reduce((s, i) => s + i.parsed.y, 0))}`,
            },
          },
        },
        scales: eixos(true),
      },
    });
  }

  // ---------- Distribuição: dia da semana ----------
  const canvasDias = document.getElementById("grafico-dias");
  if (canvasDias) {
    new Chart(canvasDias, {
      type: "bar",
      data: {
        labels: dados.dias.map((d) => d.dia),
        datasets: [{
          label: "Consultas",
          data: dados.dias.map((d) => d.total),
          backgroundColor: COR.barra,
          borderRadius: { topLeft: 4, topRight: 4 },
          borderSkipped: "bottom",
          maxBarThickness: 36,
        }],
      },
      options: {
        plugins: { legend: { display: false }, tooltip },
        scales: eixos(false),
      },
    });
  }
})();
