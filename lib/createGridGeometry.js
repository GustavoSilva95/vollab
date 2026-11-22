import { BufferAttribute, BufferGeometry } from 'three';

/**
 * Gera a grade da superfície em coordenadas de parâmetro:
 *   aGrid.x = k (log-moneyness, −1 … +1)
 *   aGrid.y = t (vencimento normalizado, 0 … 1)
 * A posição no mundo e a altura (IV) são calculadas no vertex shader.
 *
 * Retorna duas geometrias que compartilham o MESMO BufferAttribute (um único
 * buffer na GPU): `lines` tem índice de segmentos (linhas de strike e de
 * vencimento); `points` é não indexada, para cada vértice ser desenhado uma vez.
 */
export default function createGridGeometry(strikes, expiries) {
  const vertexCount = strikes * expiries;
  const grid = new Float32Array(vertexCount * 2);

  for (let j = 0; j < expiries; j++) {
    const t = j / (expiries - 1);
    for (let i = 0; i < strikes; i++) {
      const offset = (j * strikes + i) * 2;
      grid[offset] = (i / (strikes - 1)) * 2 - 1;
      grid[offset + 1] = t;
    }
  }

  const segmentCount = (strikes - 1) * expiries + strikes * (expiries - 1);
  const IndexArray = vertexCount > 65535 ? Uint32Array : Uint16Array;
  const index = new IndexArray(segmentCount * 2);
  let n = 0;

  for (let j = 0; j < expiries; j++) {
    for (let i = 0; i < strikes; i++) {
      const v = j * strikes + i;
      if (i < strikes - 1) {
        index[n++] = v; // ao longo do strike (smile de um vencimento)
        index[n++] = v + 1;
      }
      if (j < expiries - 1) {
        index[n++] = v; // ao longo do vencimento (estrutura a termo de um strike)
        index[n++] = v + strikes;
      }
    }
  }

  const gridAttribute = new BufferAttribute(grid, 2);

  // `position` é obrigatório para o three.js (bounding sphere / draw count);
  // usamos um buffer zerado e desligamos o frustum culling nos objetos.
  const positionAttribute = new BufferAttribute(new Float32Array(vertexCount * 3), 3);

  const lines = new BufferGeometry();
  lines.setAttribute('position', positionAttribute);
  lines.setAttribute('aGrid', gridAttribute);
  lines.setIndex(new BufferAttribute(index, 1));

  const points = new BufferGeometry();
  points.setAttribute('position', positionAttribute);
  points.setAttribute('aGrid', gridAttribute);

  return {
    lines,
    points,
    dispose() {
      lines.dispose();
      points.dispose();
    },
  };
}
