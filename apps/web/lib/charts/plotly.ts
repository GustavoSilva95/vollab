/**
 * Pacote parcial do Plotly (ADR-12, PRD-UI-06): só o núcleo e os traços usados no cockpit.
 * Importado apenas por `PlotClient`, que é carregado com `next/dynamic` e `ssr: false`:
 * o Plotly nunca entra no bundle inicial (PRD-NF-07).
 */
import Plotly from 'plotly.js/lib/core';
import bar from 'plotly.js/lib/bar';
import scatter from 'plotly.js/lib/scatter';

Plotly.register([scatter, bar]);

export default Plotly;
