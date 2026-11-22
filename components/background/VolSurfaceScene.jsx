'use client';

import { useEffect, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { PerformanceMonitor } from '@react-three/drei';
import { Vector3 } from 'three';
import VolSurfaceMesh from './VolSurfaceMesh';
import Starfield from './Starfield';
import AxisLabels from './AxisLabels';
import styles from './VolSurfaceBackground.module.css';

/** Maior salto de tempo aceito por quadro (evita "pulos" ao voltar de uma pausa). */
const MAX_FRAME_DELTA = 0.1;

/** Avança o relógio da simulação antes dos demais `useFrame` (prioridade negativa). */
function SimulationClock({ timeRef, animate }) {
  useFrame((_, delta) => {
    if (animate) timeRef.current += Math.min(delta, MAX_FRAME_DELTA);
  }, -1);
  return null;
}

/** Câmera fixa em 3/4 + parallax suave com o mouse (amortecido). */
function CameraRig({ config, parallaxEnabled, isMobile }) {
  const camera = useThree((state) => state.camera);
  const pointer = useRef({ x: 0, y: 0 });
  const offset = useRef({ x: 0, y: 0 });
  const base = useRef(new Vector3(...config.camera.position));
  const target = useRef(new Vector3(...config.camera.target));

  useEffect(() => {
    const { position, target: lookAt, mobilePosition, mobileTarget } = config.camera;
    base.current.fromArray(isMobile ? mobilePosition : position);
    target.current.fromArray(isMobile ? mobileTarget : lookAt);
  }, [config, isMobile]);

  useEffect(() => {
    if (!parallaxEnabled) {
      pointer.current.x = 0;
      pointer.current.y = 0;
      return undefined;
    }
    const onPointerMove = (event) => {
      pointer.current.x = (event.clientX / window.innerWidth) * 2 - 1;
      pointer.current.y = (event.clientY / window.innerHeight) * 2 - 1;
    };
    window.addEventListener('pointermove', onPointerMove, { passive: true });
    return () => window.removeEventListener('pointermove', onPointerMove);
  }, [parallaxEnabled]);

  useFrame((_, delta) => {
    const { parallax, parallaxDamping } = config.motion;
    // Amortecimento exponencial independente de FPS.
    const k = 1 - Math.exp(-parallaxDamping * Math.min(delta, MAX_FRAME_DELTA));
    offset.current.x += (pointer.current.x * parallax - offset.current.x) * k;
    offset.current.y += (-pointer.current.y * parallax * 0.5 - offset.current.y) * k;

    camera.position.set(
      base.current.x + offset.current.x,
      base.current.y + offset.current.y,
      base.current.z,
    );
    camera.lookAt(target.current);
  });

  return null;
}

/** Balanço lento da superfície em torno do eixo Y. */
function SurfaceGroup({ config, timeRef, children }) {
  const group = useRef(null);
  useFrame(() => {
    if (!group.current) return;
    const { yawAmplitude, yawSpeed } = config.motion;
    group.current.rotation.y = yawAmplitude * Math.sin(timeRef.current * yawSpeed);
  });
  return <group ref={group}>{children}</group>;
}

export default function VolSurfaceScene({
  config,
  frameloop,
  animate,
  isMobile,
  parallaxEnabled,
  onReady,
}) {
  const timeRef = useRef(animate ? 0 : config.motion.staticTime);
  const [dpr, setDpr] = useState(config.render.dpr[1]);
  const [degraded, setDegraded] = useState(false);

  const density = degraded ? 'low' : isMobile ? 'mobile' : 'desktop';

  const degrade = () => {
    setDpr(config.render.lowDpr);
    setDegraded(true);
  };

  return (
    <Canvas
      className={styles.canvas}
      frameloop={frameloop}
      dpr={[config.render.dpr[0], dpr]}
      gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
      camera={{ fov: config.camera.fov, near: 0.1, far: 200, position: config.camera.position }}
      onCreated={({ gl }) => {
        gl.setClearColor(config.colors.background, 1);
        onReady?.();
      }}
      aria-hidden="true"
      tabIndex={-1}
    >
      {animate && (
        <PerformanceMonitor
          // Recupera o DPR quando o FPS volta, mas mantém a grade reduzida
          // (trocar a densidade várias vezes causaria "piscadas").
          onIncline={() => setDpr(config.render.dpr[1])}
          onDecline={degrade}
          flipflops={3}
          onFallback={degrade}
        />
      )}
      <SimulationClock timeRef={timeRef} animate={animate} />
      <CameraRig config={config} parallaxEnabled={parallaxEnabled} isMobile={isMobile} />
      <Starfield config={config} density={density} timeRef={timeRef} />
      <SurfaceGroup config={config} timeRef={timeRef}>
        <VolSurfaceMesh config={config} density={density} timeRef={timeRef} />
        {config.axisLabels.enabled && !isMobile && <AxisLabels config={config} />}
      </SurfaceGroup>
    </Canvas>
  );
}
