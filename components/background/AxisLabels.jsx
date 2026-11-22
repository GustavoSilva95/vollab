'use client';

import { useEffect, useMemo } from 'react';
import { CanvasTexture, LinearFilter, SpriteMaterial } from 'three';

const FONT_PX = 48;
const LETTER_SPACING_PX = 10;
/** Altura do rótulo em unidades da cena. */
const WORLD_HEIGHT = 0.1;

/** Desenha o texto num canvas e devolve textura + proporção. */
function createLabelTexture(text, color) {
  const fontFamily =
    getComputedStyle(document.body).getPropertyValue('--font-mono').trim() || 'ui-monospace, monospace';
  const font = `500 ${FONT_PX}px ${fontFamily}, ui-monospace, monospace`;

  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  ctx.font = font;
  ctx.letterSpacing = `${LETTER_SPACING_PX}px`;
  const width = Math.ceil(ctx.measureText(text).width) + 8;
  const height = Math.ceil(FONT_PX * 1.4);

  canvas.width = width;
  canvas.height = height;
  ctx.font = font; // o redimensionamento reseta o contexto
  ctx.letterSpacing = `${LETTER_SPACING_PX}px`;
  ctx.fillStyle = color;
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 4, height / 2);

  const texture = new CanvasTexture(canvas);
  texture.minFilter = LinearFilter;
  return { texture, aspect: width / height };
}

function AxisLabel({ text, position, color, opacity }) {
  const { material, aspect } = useMemo(() => {
    const { texture, aspect: ratio } = createLabelTexture(text, color);
    const spriteMaterial = new SpriteMaterial({
      map: texture,
      transparent: true,
      opacity,
      depthWrite: false,
      depthTest: false,
      fog: false,
    });
    return { material: spriteMaterial, aspect: ratio };
  }, [text, color, opacity]);

  useEffect(
    () => () => {
      material.map?.dispose();
      material.dispose();
    },
    [material],
  );

  return <sprite material={material} position={position} scale={[WORLD_HEIGHT * aspect, WORLD_HEIGHT, 1]} />;
}

/** Rótulos discretos dos três eixos da superfície. */
export default function AxisLabels({ config }) {
  const { width, depth } = config.surface;
  const { opacity } = config.axisLabels;
  const color = config.colors.high;
  return (
    <>
      {/* Coordenadas locais da superfície (X = strike, Z = vencimento), pairando atrás
          da borda de vencimentos longos, na região visível ao lado do texto do hero. */}
      <AxisLabel text="STRIKE" position={[0.6, 0.15, -depth / 2 - 0.5]} color={color} opacity={opacity} />
      <AxisLabel text="VENCIMENTO" position={[width / 2 - 2.1, 0.1, -depth / 3]} color={color} opacity={opacity} />
      <AxisLabel text="IV" position={[-1.2, 1.2, -depth / 2 - 0.2]} color={color} opacity={opacity} />
    </>
  );
}
