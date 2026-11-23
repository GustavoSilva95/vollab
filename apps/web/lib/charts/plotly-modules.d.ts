// Tipos dos módulos parciais do Plotly (PRD-UI-06): o núcleo tem a API de `plotly.js`.
declare module 'plotly.js/lib/core' {
  import * as Plotly from 'plotly.js';
  const core: typeof Plotly & { register(modules: unknown[]): void };
  export default core;
}
declare module 'plotly.js/lib/scatter' {
  const trace: unknown;
  export default trace;
}
declare module 'plotly.js/lib/bar' {
  const trace: unknown;
  export default trace;
}
