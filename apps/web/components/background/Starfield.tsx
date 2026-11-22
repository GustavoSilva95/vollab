'use client';

import { useEffect, useMemo, useRef, type RefObject } from 'react';
import { useFrame } from '@react-three/fiber';
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  LinearSRGBColorSpace,
  Points,
  ShaderMaterial,
} from 'three';
import type { Density, VolSurfaceConfig } from '@/lib/volSurfaceConfig';
import starsVertexShader from './shaders/stars.vert';
import starsFragmentShader from './shaders/stars.frag';

const STAR_SEED = 20251121;

/** PRNG determinístico (mulberry32): o céu é sempre o mesmo entre recargas. */
function createRandom(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function createStarGeometry(count: number, radius: number, thickness: number): BufferGeometry {
  const random = createRandom(STAR_SEED);
  const positions = new Float32Array(count * 3);
  const seeds = new Float32Array(count);
  const scales = new Float32Array(count);

  for (let i = 0; i < count; i++) {
    // Direção uniforme na esfera + raio dentro da casca.
    const u = random() * 2 - 1;
    const theta = random() * Math.PI * 2;
    const r = radius + random() * thickness;
    const s = Math.sqrt(1 - u * u);
    positions[i * 3] = r * s * Math.cos(theta);
    positions[i * 3 + 1] = r * u;
    positions[i * 3 + 2] = r * s * Math.sin(theta);
    seeds[i] = random();
    scales[i] = 0.5 + random() ** 3 * 1.8; // maioria pequena, poucas maiores
  }

  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new BufferAttribute(positions, 3));
  geometry.setAttribute('aSeed', new BufferAttribute(seeds, 1));
  geometry.setAttribute('aScale', new BufferAttribute(scales, 1));
  return geometry;
}

export interface SceneLayerProps {
  config: VolSurfaceConfig;
  density: Density;
  timeRef: RefObject<number>;
}

export default function Starfield({ config, density, timeRef }: SceneLayerProps) {
  const { stars, colors } = config;
  const count = stars.count[density];

  const geometry = useMemo(
    () => createStarGeometry(count, stars.radius, stars.thickness),
    [count, stars.radius, stars.thickness],
  );
  useEffect(() => () => geometry.dispose(), [geometry]);

  const material = useMemo(
    () =>
      new ShaderMaterial({
        vertexShader: starsVertexShader,
        fragmentShader: starsFragmentShader,
        uniforms: {
          uTime: { value: 0 },
          uSize: { value: stars.size },
          uPixelRatio: { value: 1 },
          uTwinkleSpeed: { value: stars.twinkleSpeed },
          uOpacity: { value: stars.opacity },
          uColor: { value: new Color().setStyle(colors.high, LinearSRGBColorSpace) },
        },
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
      }),
    [stars, colors.high],
  );
  useEffect(() => () => material.dispose(), [material]);

  const pointsRef = useRef<Points<BufferGeometry, ShaderMaterial>>(null);
  useFrame((state) => {
    if (!pointsRef.current) return;
    const { uniforms } = pointsRef.current.material;
    uniforms.uTime!.value = timeRef.current;
    uniforms.uPixelRatio!.value = state.gl.getPixelRatio();
  });

  return <points ref={pointsRef} geometry={geometry} material={material} frustumCulled={false} />;
}
