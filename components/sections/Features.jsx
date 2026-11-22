import Container from '@/components/ui/Container';
import SectionTitle from '@/components/ui/SectionTitle';
import styles from './Features.module.css';

const ICON_PATHS = {
  surface: (
    <>
      <path d="M3 17c3-1 4-6 9-6s6 5 9 6" />
      <path d="M3 12c3-1 4-5 9-5s6 4 9 5" />
      <path d="M7 6.5v12M12 4v14M17 6.5v12" />
    </>
  ),
  greeks: (
    <>
      <path d="M4 20V4" />
      <path d="M4 20h16" />
      <path d="M6 17c4 0 5-10 8-10s3 6 6 6" />
    </>
  ),
  simulator: (
    <>
      <path d="M3 17h5l4-10 4 10h5" />
      <path d="M3 12h18" strokeDasharray="2 3" />
    </>
  ),
  alerts: (
    <>
      <path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4z" />
      <path d="M10 20a2 2 0 0 0 4 0" />
    </>
  ),
  risk: (
    <>
      <path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z" />
      <path d="M8.5 12.5l2.5 2.5 4.5-5" />
    </>
  ),
  journal: (
    <>
      <path d="M6 3h11a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6z" />
      <path d="M6 3a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2" />
      <path d="M9 8h6M9 12h6M9 16h3" />
    </>
  ),
};

const FEATURES = [
  {
    icon: 'surface',
    title: 'Superfície de volatilidade',
    text: 'Smile, skew e estrutura a termo do ativo em uma só leitura, com histórico para comparar regimes.',
  },
  {
    icon: 'greeks',
    title: 'Análise de gregas',
    text: 'Delta, gama, vega e theta por operação e da carteira consolidada, com atribuição diária de P&L.',
  },
  {
    icon: 'simulator',
    title: 'Simulador de estratégias',
    text: 'Monte straddles, strangles e vendas cobertas e veja o resultado em cenários de preço e volatilidade.',
  },
  {
    icon: 'alerts',
    title: 'Alertas',
    text: 'Avisos quando regras de hedge, saída ou rolagem definidas por você forem atingidas.',
  },
  {
    icon: 'risk',
    title: 'Gestão de risco',
    text: 'Dimensionamento consistente com o edge estimado, testes de estresse e limites por operação.',
  },
  {
    icon: 'journal',
    title: 'Diário de operações',
    text: 'Registro completo de cada trade e comparação entre o que foi previsto e o que de fato aconteceu.',
  },
];

function FeatureIcon({ name }) {
  return (
    <svg
      className={styles.icon}
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {ICON_PATHS[name]}
    </svg>
  );
}

export default function Features() {
  return (
    <section id="recursos" className={styles.section} aria-labelledby="recursos-title">
      <Container>
        <SectionTitle
          id="recursos-title"
          eyebrow="Recursos"
          title="Tudo o que a decisão precisa, em um só lugar"
          description="Ferramentas pensadas para o antes, o durante e o depois de cada operação com opções."
        />
        <ul className={styles.grid}>
          {FEATURES.map((feature) => (
            <li key={feature.title} className={styles.card}>
              <FeatureIcon name={feature.icon} />
              <h3 className={styles.cardTitle}>{feature.title}</h3>
              <p className={styles.cardText}>{feature.text}</p>
            </li>
          ))}
        </ul>
      </Container>
    </section>
  );
}
