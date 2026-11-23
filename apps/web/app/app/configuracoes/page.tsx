import type { Metadata } from 'next';
import ConfigView from '@/components/cockpit/config/ConfigView';
import styles from '../page.module.css';

export const metadata: Metadata = { title: 'Configurações' };

/** Configuração versionada (PRD 1.8 §8.1; BRD §7.11): casca no servidor; formulário no cliente. */
export default function ConfigPage() {
  return (
    <>
      <header className={styles.header}>
        <h1 className={styles.title}>Configurações</h1>
        <p className={styles.subtitle}>
          Custos, edge e parâmetros principais. Cada alteração cria uma versão nova; decisões e alertas gravam a versão
          vigente.
        </p>
      </header>
      <ConfigView />
    </>
  );
}
