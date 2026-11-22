import surfaceCommonGlsl from './surfaceCommon.glsl.js';

const surfaceVertexShader = /* glsl */ `
${surfaceCommonGlsl}

void main() {
  gl_Position = projectionMatrix * surfaceViewPosition();
}
`;

export default surfaceVertexShader;
