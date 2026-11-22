import colorRampGlsl from './colorRamp.glsl';

const surfaceFragmentShader = /* glsl */ `
${colorRampGlsl}

uniform float uOpacity;

varying float vHeight;
varying float vFade;

void main() {
  // Picos um pouco mais opacos que os vales.
  float alpha = uOpacity * vFade * (0.6 + 0.4 * vHeight);
  gl_FragColor = vec4(heightColor(vHeight), alpha);
}
`;

export default surfaceFragmentShader;
