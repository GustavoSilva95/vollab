import type { Metadata } from 'next';
import Image from 'next/image';
import Link from 'next/link';
import AppNav from '@/components/cockpit/AppNav';
import Providers from './providers';
import styles from './layout.module.css';

export const metadata: Metadata = {
  title: { default: 'Cockpit', template: '%s · Cockpit · Vollab' },
  robots: { index: false, follow: false },
};

/** Casca do cockpit (Server Component). Sem login na fase 1 (ADR-13). */
export default function CockpitLayout({ children }: LayoutProps<'/app'>) {
  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <Link href="/" className={styles.logo} aria-label="Vollab — página inicial">
          <Image src="/logo/logo-fundo-escuro.svg" alt="Vollab" width={72} height={28} unoptimized />
        </Link>
        <AppNav />
      </aside>
      <main id="conteudo" className={styles.main}>
        <Providers>{children}</Providers>
      </main>
    </div>
  );
}
