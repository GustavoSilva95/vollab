import Button from '@/components/ui/Button';
import Container from '@/components/ui/Container';
import { SIGNUP_HREF } from '@/components/layout/navLinks';
import styles from './CallToAction.module.css';

export default function CallToAction() {
  return (
    <section id="planos" className={styles.section} aria-labelledby="cta-title">
      <Container>
        <div className={styles.box}>
          <p className={`${styles.eyebrow} mono`}>Planos</p>
          <h2 id="cta-title" className={styles.title}>
            Opere com método, não com palpite
          </h2>
          <p className={styles.text}>
            Crie sua conta e acompanhe a abertura dos planos. Avisaremos quando novas funcionalidades estiverem
            disponíveis.
          </p>
          <div className={styles.ctas}>
            <Button href={SIGNUP_HREF} size="lg">
              Criar conta
            </Button>
            <Button href="#recursos" variant="ghost" size="lg">
              Ver recursos
            </Button>
          </div>
        </div>
      </Container>
    </section>
  );
}
