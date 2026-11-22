import VolSurfaceBackground from '@/components/background/VolSurfaceBackground';
import Button from '@/components/ui/Button';
import Container from '@/components/ui/Container';
import { SIGNUP_HREF } from '@/components/layout/navLinks';
import styles from './Hero.module.css';

// Valores fictícios, apenas para ilustrar o tipo de leitura da plataforma.
const SAMPLE_METRICS = [
  { label: 'IV Rank', value: '62' },
  { label: 'Skew 25Δ', value: '−4,8 pp' },
  { label: 'Term 1M/3M', value: '+1,9 pp' },
];

export default function Hero() {
  return (
    <section className={styles.hero} aria-labelledby="hero-title">
      <VolSurfaceBackground />

      <Container className={styles.inner}>
        <div className={styles.content}>
          <p className={`${styles.eyebrow} mono`}>Volatilidade · Gregas · Risco</p>
          <h1 id="hero-title" className={styles.title}>
            Leia a volatilidade antes do mercado
          </h1>
          <p className={styles.subtitle}>
            Compare volatilidade implícita e realizada, meça o edge líquido de custos e acompanhe o risco de
            cada operação com opções — da análise ao diário.
          </p>

          <div className={styles.ctas}>
            <Button href={SIGNUP_HREF} size="lg">
              Começar agora
            </Button>
            <Button href="#como-funciona" variant="ghost" size="lg">
              Como funciona
            </Button>
          </div>

          <div className={styles.metrics}>
            <dl className={`${styles.metricList} mono`}>
              {SAMPLE_METRICS.map((metric) => (
                <div key={metric.label} className={styles.metric}>
                  <dt>{metric.label}</dt>
                  <dd>{metric.value}</dd>
                </div>
              ))}
            </dl>
            <p className={`${styles.metricNote} mono`}>Valores ilustrativos</p>
          </div>
        </div>
      </Container>
    </section>
  );
}
