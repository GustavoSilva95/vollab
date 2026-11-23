import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import AssetView from '@/components/cockpit/vol/AssetView';
import styles from '../../page.module.css';

const TICKER = /^[A-Z0-9]{4,12}$/;

export async function generateMetadata({ params }: PageProps<'/app/ativos/[ticker]'>): Promise<Metadata> {
  const { ticker } = await params;
  return { title: ticker.toUpperCase() };
}

/**
 * Tela do ativo (PRD §8.1): casca no servidor; gráficos e tabelas no cliente (Plotly só no
 * navegador), com dados D-1 já calculados pelo worker.
 */
export default async function AssetPage({ params }: PageProps<'/app/ativos/[ticker]'>) {
  const { ticker: raw } = await params;
  const ticker = raw.toUpperCase();
  if (!TICKER.test(ticker)) notFound();
  return (
    <>
      <header className={styles.header}>
        <p className={styles.subtitle}>
          <Link href="/app/ativos">Ativos</Link> /
        </p>
        <h1 className={styles.title}>{ticker}</h1>
      </header>
      <AssetView ticker={ticker} />
    </>
  );
}
