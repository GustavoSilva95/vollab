import noiseGlsl from './noise.glsl.js';

/**
 * Trecho compartilhado pelos shaders de linhas e de pontos: calcula a IV de
 * cada vértice e sua posição no mundo. Mantê-lo num só lugar garante que
 * linhas e pontos fiquem exatamente sobrepostos.
 */
const surfaceCommonGlsl = /* glsl */ `
attribute vec2 aGrid;   // x = k (log-moneyness), y = t (vencimento normalizado)

uniform float uTime;
uniform float uBase;
uniform float uSkew;
uniform float uSmile;
uniform float uDecay;
uniform float uTerm;
uniform float uAmp;
uniform float uNoiseFreq;
uniform float uNoiseSpeed;
uniform vec3  uSize;      // largura (X), escala de altura (Y), profundidade (Z)
uniform vec2  uIvRange;   // faixa de IV mapeada para 0..1
uniform float uEdgeFade;
uniform float uFogNear;
uniform float uFogFar;

varying float vHeight;    // IV normalizada (0 = vale, 1 = pico)
varying float vFade;      // esmaecimento combinado: bordas da grade × profundidade

${noiseGlsl}

// Volatilidade implícita no ponto (k, t):
//   base                       nível médio
//   skew·k                     inclinação; skew < 0 deixa as puts (k < 0) mais caras
//   smile·k²·e^(−decay·t)      convexidade, mais forte nos vencimentos curtos
//   term·(1 − e^(−3t))         estrutura a termo: sobe (contango) ou cai (backwardation)
//   amp·noise(k, t, tempo)     "respiração" lenta, contínua no tempo
float impliedVol(float k, float t) {
  float iv = uBase
           + uSkew * k
           + uSmile * k * k * exp(-uDecay * t)
           + uTerm * (1.0 - exp(-t * 3.0))
           + uAmp * snoise(vec3(k * uNoiseFreq, t * uNoiseFreq, uTime * uNoiseSpeed));
  return iv;
}

// Retorna a posição em espaço de visão e preenche vHeight/vFade.
vec4 surfaceViewPosition() {
  float k = aGrid.x;
  float t = aGrid.y;
  float iv = impliedVol(k, t);

  vec3 world = vec3(
    k * 0.5 * uSize.x,
    (iv - uBase) * uSize.y,
    (0.5 - t) * uSize.z      // vencimentos curtos mais perto da câmera
  );

  vHeight = clamp((iv - uIvRange.x) / (uIvRange.y - uIvRange.x), 0.0, 1.0);

  // Distância até a borda mais próxima da grade, em fração (0 na borda).
  float edge = min(1.0 - abs(k), min(t, 1.0 - t) * 2.0);
  float edgeFade = smoothstep(0.0, uEdgeFade, edge);

  vec4 mv = modelViewMatrix * vec4(world, 1.0);
  float depthFade = 1.0 - smoothstep(uFogNear, uFogFar, -mv.z);
  vFade = edgeFade * depthFade;

  return mv;
}
`;

export default surfaceCommonGlsl;
