const starsFragmentShader = /* glsl */ `
uniform vec3 uColor;
uniform float uOpacity;

varying float vTwinkle;

void main() {
  float d = length(gl_PointCoord - 0.5) * 2.0;
  if (d > 1.0) discard;
  float alpha = uOpacity * vTwinkle * pow(1.0 - d, 1.6);
  gl_FragColor = vec4(uColor, alpha);
}
`;

export default starsFragmentShader;
