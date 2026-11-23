import type { Metadata } from 'next';
import EventsManager from '@/components/cockpit/events/EventsManager';
import styles from '../page.module.css';

export const metadata: Metadata = { title: 'Eventos' };

/** Calendário de eventos (PRD §8.1, RF-EVT-01/02): CRUD com TanStack Query e React Hook Form + Zod. */
export default function EventsPage() {
  return (
    <>
      <header className={styles.header}>
        <h1 className={styles.title}>Eventos</h1>
        <p className={styles.subtitle}>
          Resultados, datas ex-dividendo e ex-JCP, Copom e eventos macro. Vencimentos de opções aparecem a partir das
          séries coletadas.
        </p>
      </header>
      <EventsManager />
    </>
  );
}
