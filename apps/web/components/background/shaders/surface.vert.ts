import surfaceCommonGlsl from './surfaceCommon.glsl';

const surfaceVertexShader = /* glsl */ `
${surfaceCommonGlsl}

void main() {
  gl_Position = projectionMatrix * surfaceViewPosition();
}
`;

export default surfaceVertexShader;
