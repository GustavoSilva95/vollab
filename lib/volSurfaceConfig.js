/**
 * Configuração central da superfície de volatilidade animada do fundo da home.
 * Tudo o que é ajustável visualmente mora aqui; os componentes só leem estes valores.
 */

const volSurfaceConfig = {
  /** Densidade da grade (vértices) por nível de qualidade. */
  grid: {
    desktop: { strikes: 80, expiries: 50 },
    mobile: { strikes: 48, expiries: 30 },
    /** Usado quando o PerformanceMonitor detecta queda de FPS. */
    low: { strikes: 40, expiries: 24 },
  },

  /** Breakpoint (px) abaixo do qual usamos a densidade "mobile". */
  mobileBreakpoint: 640,

  /** Dimensões da superfície no espaço da cena (unidades do three.js). */
  surface: {
    width: 9, // extensão em strike (eixo X)
    depth: 6, // extensão em vencimento (eixo Z)
    heightScale: 7, // quantas unidades de Y por 1,00 (100 pontos) de IV
    /** Faixa de IV usada para normalizar cor/brilho (0 = vale, 1 = pico). */
    ivRange: [0.14, 0.5],
    /** Largura (em fração da grade) do esmaecimento nas bordas. */
    edgeFade: 0.14,
  },

  /**
   * Forma da IV:
   *   iv = base + skew·k + smile·k²·e^(−decay·t) + term·(1 − e^(−3t)) + amp·noise
   * Cada parâmetro oscilante é `center + swing · sin(2π·time / period + phase)`.
   */
  iv: {
    base: 0.24,
    skew: { center: -0.07, swing: 0.035, period: 31, phase: 0 },
    smile: { center: 0.16, swing: 0.06, period: 23, phase: 1.7 },
    term: { center: 0.04, swing: 0.05, period: 37, phase: 3.1 },
    decay: 2.4,
    noise: {
      amp: 0.028,
      frequency: 1.6, // escala espacial do ruído (k e t)
      speed: 0.07, // velocidade da "respiração"
    },
  },

  /** Cores (hex). Espelham as variáveis de app/globals.css. */
  colors: {
    low: '#555555',
    high: '#F7F7F7',
    accent: '#7FD1C7',
    /** A partir de qual altura normalizada o acento começa a aparecer. */
    accentThreshold: 0.86,
    background: '#0D0D12',
  },

  lines: {
    opacity: 0.55,
  },

  points: {
    size: 5, // tamanho base (px, antes do DPR e da perspectiva)
    peakBoost: 1.6, // multiplicador extra nos picos
    opacity: 0.9,
  },

  /** Esmaecimento por profundidade (distância à câmera). */
  fog: {
    near: 7,
    far: 19,
  },

  stars: {
    count: { desktop: 1200, mobile: 600, low: 450 },
    radius: 40, // raio interno da casca esférica
    thickness: 25, // espessura da casca
    size: 1.6,
    twinkleSpeed: 0.9,
    opacity: 0.7,
  },

  camera: {
    fov: 42,
    position: [4.6, 3.2, 6.2],
    target: [-1.4, -0.1, 0], // deslocado à esquerda: a superfície fica à direita, longe do texto
    /** Em telas estreitas a superfície fica centralizada e um pouco mais distante. */
    mobilePosition: [5.2, 4.4, 9.4],
    mobileTarget: [0, -2.6, 0], // alvo abaixo da superfície: ela sobe para o topo da tela
  },

  motion: {
    /** Balanço lento em Y da superfície (radianos e rad/s). */
    yawAmplitude: 0.35,
    yawSpeed: 0.06,
    /** Deslocamento máximo da câmera com o mouse (unidades da cena). */
    parallax: 0.6,
    /** Fator de suavização do parallax por segundo (maior = mais rápido). */
    parallaxDamping: 2.2,
    /** Tempo fixo exibido quando o usuário prefere movimento reduzido. */
    staticTime: 12,
  },

  render: {
    dpr: [1, 1.75],
    /** DPR usado após queda de desempenho. */
    lowDpr: 1,
  },

  /** Quanto do scroll (em alturas de viewport) até o fundo sumir por completo. */
  scrollFadeViewports: 0.9,

  axisLabels: {
    enabled: true,
    opacity: 0.4,
  },
};

export default volSurfaceConfig;
