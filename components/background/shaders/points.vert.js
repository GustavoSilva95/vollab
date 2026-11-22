import surfaceCommonGlsl from './surfaceCommon.glsl.js';

const pointsVertexShader = /* glsl */ `
${surfaceCommonGlsl}

uniform float uPointSize;
uniform float uPeakBoost;
uniform float uPixelRatio;

void main() {
  vec4 mv = surfaceViewPosition();
  gl_Position = projectionMatrix * mv;

  // Tamanho cresce com a IV e diminui com a distância (perspectiva).
  float size = uPointSize * (0.45 + uPeakBoost * vHeight * vHeight);
  gl_PointSize = size * uPixelRatio * (9.0 / -mv.z);
}
`;

export default pointsVertexShader;
