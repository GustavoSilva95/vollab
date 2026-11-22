'use client';

import { useEffect, useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { AdditiveBlending, Color, LinearSRGBColorSpace, NormalBlending, ShaderMaterial } from 'three';
import createGridGeometry from '@/lib/createGridGeometry';
import surfaceVertexShader from './shaders/surface.vert.js';
import surfaceFragmentShader from './shaders/surface.frag.js';
import pointsVertexShader from './shaders/points.vert.js';
import pointsFragmentShader from './shaders/points.frag.js';

const TWO_PI = Math.PI * 2;

/**
 * ShaderMaterial não aplica conversão de cor na saída, então passamos os hex
 * "crus" (sem converter para linear) para que apareçam exatamente como no CSS.
 */
function rawColor(hex) {
  return new Color().setStyle(hex, LinearSRGBColorSpace);
}

/** center + swing · sin(2π·time/period + phase) */
function oscillate({ center, swing, period, phase }, time) {
  return center + swing * Math.sin((TWO_PI * time) / period + phase);
}

function createSharedUniforms(config) {
  const { surface, iv, colors, fog } = config;
  return {
    uTime: { value: 0 },
    uBase: { value: iv.base },
    uSkew: { value: iv.skew.center },
    uSmile: { value: iv.smile.center },
    uDecay: { value: iv.decay },
    uTerm: { value: iv.term.center },
    uAmp: { value: iv.noise.amp },
    uNoiseFreq: { value: iv.noise.frequency },
    uNoiseSpeed: { value: iv.noise.speed },
    uSize: { value: [surface.width, surface.heightScale, surface.depth] },
    uIvRange: { value: surface.ivRange },
    uEdgeFade: { value: surface.edgeFade },
    uFogNear: { value: fog.near },
    uFogFar: { value: fog.far },
    uColorLow: { value: rawColor(colors.low) },
    uColorHigh: { value: rawColor(colors.high) },
    uColorAccent: { value: rawColor(colors.accent) },
    uAccentThreshold: { value: colors.accentThreshold },
  };
}

export default function VolSurfaceMesh({ config, density, timeRef }) {
  const { strikes, expiries } = config.grid[density];

  const grid = useMemo(() => createGridGeometry(strikes, expiries), [strikes, expiries]);
  useEffect(() => () => grid.dispose(), [grid]);

  const { lineMaterial, pointMaterial } = useMemo(() => {
    const sharedUniforms = createSharedUniforms(config);

    const lines = new ShaderMaterial({
      vertexShader: surfaceVertexShader,
      fragmentShader: surfaceFragmentShader,
      uniforms: { ...sharedUniforms, uOpacity: { value: config.lines.opacity } },
      transparent: true,
      depthWrite: false,
      blending: NormalBlending,
    });

    const points = new ShaderMaterial({
      vertexShader: pointsVertexShader,
      fragmentShader: pointsFragmentShader,
      uniforms: {
        ...sharedUniforms,
        uOpacity: { value: config.points.opacity },
        uPointSize: { value: config.points.size },
        uPeakBoost: { value: config.points.peakBoost },
        uPixelRatio: { value: 1 },
      },
      transparent: true,
      depthWrite: false,
      blending: AdditiveBlending,
    });

    return { lineMaterial: lines, pointMaterial: points };
  }, [config]);

  useEffect(
    () => () => {
      lineMaterial.dispose();
      pointMaterial.dispose();
    },
    [lineMaterial, pointMaterial],
  );

  const linesRef = useRef(null);
  const pointsRef = useRef(null);

  // Só escreve números em uniforms existentes: nenhuma alocação por quadro.
  // Os uniforms comuns são os mesmos objetos nos dois materiais.
  useFrame((state) => {
    if (!linesRef.current || !pointsRef.current) return;
    const shared = linesRef.current.material.uniforms;
    const time = timeRef.current;
    shared.uTime.value = time;
    shared.uSkew.value = oscillate(config.iv.skew, time);
    shared.uSmile.value = oscillate(config.iv.smile, time);
    shared.uTerm.value = oscillate(config.iv.term, time);
    pointsRef.current.material.uniforms.uPixelRatio.value = state.gl.getPixelRatio();
  });

  return (
    <>
      <lineSegments ref={linesRef} geometry={grid.lines} material={lineMaterial} frustumCulled={false} />
      <points ref={pointsRef} geometry={grid.points} material={pointMaterial} frustumCulled={false} />
    </>
  );
}
