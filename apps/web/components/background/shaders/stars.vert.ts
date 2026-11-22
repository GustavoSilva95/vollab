const starsVertexShader = /* glsl */ `
attribute float aSeed;
attribute float aScale;

uniform float uTime;
uniform float uSize;
uniform float uPixelRatio;
uniform float uTwinkleSpeed;

varying float vTwinkle;

void main() {
  // Cintilação: seno com fase e velocidade próprias por estrela.
  float speed = uTwinkleSpeed * (0.6 + aSeed * 0.8);
  vTwinkle = 0.55 + 0.45 * sin(uTime * speed + aSeed * 6.2831);

  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = uSize * aScale * uPixelRatio;
}
`;

export default starsVertexShader;
