'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { COCKPIT_ROUTES, isActiveRoute } from '@/lib/cockpit/routes';
import styles from './AppNav.module.css';

export default function AppNav() {
  const pathname = usePathname();

  return (
    <nav className={styles.nav} aria-label="Cockpit">
      <ul className={styles.list}>
        {COCKPIT_ROUTES.map((route) => {
          if (!route.available) {
            return (
              <li key={route.href}>
                <span className={styles.disabled} aria-disabled="true" title={`Disponível na Etapa ${route.stage}`}>
                  {route.label}
                  <span className={`${styles.stage} mono`}>E{route.stage}</span>
                </span>
              </li>
            );
          }
          const active = isActiveRoute(pathname, route.href);
          return (
            <li key={route.href}>
              <Link
                href={route.href}
                className={styles.link}
                aria-current={active ? 'page' : undefined}
                data-active={active || undefined}
              >
                {route.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
