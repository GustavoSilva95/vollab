import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import PositionView from '@/components/cockpit/journal/PositionView';
import styles from '../../page.module.css';

const ID = /^[1-9]\d{0,17}$/;

export async function generateMetadata({ params }: PageProps<'/app/operacoes/[id]'>): Promise<Metadata> {
  const { id } = await params;
  return { title: `Operação ${id}` };
}

/**
 * Operação (PRD 1.10 §8.1): casca no servidor; detalhe, lançamentos, marcação e atribuição no
 * cliente (o formulário de lançamento muda os dados e o gráfico usa Plotly só no navegador).
 */
export default async function PositionPage({ params }: PageProps<'/app/operacoes/[id]'>) {
  const { id } = await params;
  if (!ID.test(id)) notFound();
  return (
    <>
      <header className={styles.header}>
        <p className={styles.subtitle}>
          <Link href="/app/diario">Diário</Link> /
        </p>
        <h1 className={styles.title}>Operação {id}</h1>
      </header>
      <PositionView id={Number(id)} />
    </>
  );
}
