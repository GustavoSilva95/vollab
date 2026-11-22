import Image from 'next/image';
import Link from 'next/link';
import Button from '@/components/ui/Button';
import Container from '@/components/ui/Container';
import styles from './ComingSoon.module.css';

/** Página provisória para rotas ainda não implementadas (login, cadastro). */
export default function ComingSoon({ title, description }) {
  return (
    <main className={styles.page}>
      <Container className={styles.inner}>
        <Link href="/" className={styles.logo} aria-label="Vollab — página inicial">
          <Image src="/logo/logo-fundo-escuro.svg" alt="Vollab" width={72} height={28} unoptimized />
        </Link>
        <p className={`${styles.eyebrow} mono`}>Em breve</p>
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.text}>{description}</p>
        <Button href="/" variant="ghost" size="lg">
          Voltar para a página inicial
        </Button>
      </Container>
    </main>
  );
}
