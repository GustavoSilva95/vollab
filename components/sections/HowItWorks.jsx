import Container from '@/components/ui/Container';
import SectionTitle from '@/components/ui/SectionTitle';
import styles from './HowItWorks.module.css';

const STEPS = [
  {
    title: 'Escolha seus ativos',
    text: 'Selecione os ativos-objeto que você acompanha. A plataforma organiza volatilidade implícita e realizada de cada um.',
  },
  {
    title: 'Avalie a oportunidade',
    text: 'Veja se a volatilidade está cara ou barata, com intervalo de confiança e custos descontados, e simule a estrutura.',
  },
  {
    title: 'Acompanhe e registre',
    text: 'Registre a operação feita na sua corretora, monitore gregas e limites e revise o resultado no diário.',
  },
];

export default function HowItWorks() {
  return (
    <section id="como-funciona" className={styles.section} aria-labelledby="como-funciona-title">
      <Container>
        <SectionTitle
          id="como-funciona-title"
          eyebrow="Como funciona"
          title="Três passos, do estudo ao registro"
          description="A Vollab não executa ordens: você decide e opera na sua corretora; nós apoiamos a análise e o acompanhamento."
        />
        <ol className={styles.steps}>
          {STEPS.map((step, index) => (
            <li key={step.title} className={styles.step}>
              <span className={`${styles.number} mono`} aria-hidden="true">
                {String(index + 1).padStart(2, '0')}
              </span>
              <h3 className={styles.stepTitle}>{step.title}</h3>
              <p className={styles.stepText}>{step.text}</p>
            </li>
          ))}
        </ol>
      </Container>
    </section>
  );
}
