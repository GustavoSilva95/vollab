import colorRampGlsl from './colorRamp.glsl.js';

const pointsFragmentShader = /* glsl */ `
${colorRampGlsl}

uniform float uOpacity;

varying float vHeight;
varying float vFade;

void main() {
  // Disco com núcleo brilhante e halo suave.
  float d = length(gl_PointCoord - 0.5) * 2.0;
  if (d > 1.0) discard;
  float glow = pow(1.0 - d, 1.6);

  float brightness = 0.35 + 0.65 * vHeight;
  float alpha = uOpacity * glow * brightness * vFade;
  gl_FragColor = vec4(heightColor(vHeight), alpha); // blending aditivo: cor × alpha + destino
}
`;

export default pointsFragmentShader;
