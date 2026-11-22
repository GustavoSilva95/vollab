/** Cor por altura: cinza (#555) nos vales → branco nos picos → acento só nos extremos. */
const colorRampGlsl = /* glsl */ `
uniform vec3 uColorLow;
uniform vec3 uColorHigh;
uniform vec3 uColorAccent;
uniform float uAccentThreshold;

vec3 heightColor(float h) {
  vec3 c = mix(uColorLow, uColorHigh, smoothstep(0.0, 1.0, h));
  float accent = smoothstep(uAccentThreshold, 1.0, h);
  return mix(c, uColorAccent, accent * 0.85);
}
`;

export default colorRampGlsl;
