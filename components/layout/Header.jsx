'use client';

import { useEffect, useId, useRef, useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import Button from '@/components/ui/Button';
import Container from '@/components/ui/Container';
import { LOGIN_HREF, NAV_LINKS, SIGNUP_HREF } from './navLinks';
import styles from './Header.module.css';

const SCROLL_THRESHOLD = 8;
const DESKTOP_QUERY = '(min-width: 960px)';

export default function Header() {
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const toggleRef = useRef(null);
  const panelRef = useRef(null);
  const panelId = useId();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > SCROLL_THRESHOLD);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // Menu aberto: trava o scroll, fecha com Esc e ao passar para o layout desktop.
  useEffect(() => {
    if (!menuOpen) return undefined;

    const toggle = toggleRef.current;
    const desktop = window.matchMedia(DESKTOP_QUERY);
    const close = () => setMenuOpen(false);
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        close();
        toggle?.focus();
      }
    };

    document.documentElement.style.overflow = 'hidden';
    panelRef.current?.querySelector('a')?.focus();
    document.addEventListener('keydown', onKeyDown);
    desktop.addEventListener('change', close);

    return () => {
      document.documentElement.style.overflow = '';
      document.removeEventListener('keydown', onKeyDown);
      desktop.removeEventListener('change', close);
    };
  }, [menuOpen]);

  const closeMenu = () => setMenuOpen(false);

  return (
    <header className={styles.header} data-solid={scrolled || menuOpen || undefined}>
      <Container className={styles.bar}>
        <Link href="/" className={styles.logo} aria-label="Vollab — página inicial" onClick={closeMenu}>
          <Image src="/logo/logo-fundo-escuro.svg" alt="Vollab" width={72} height={28} priority unoptimized />
        </Link>

        <nav className={styles.nav} aria-label="Principal">
          <ul className={styles.navList}>
            {NAV_LINKS.map((link) => (
              <li key={link.href}>
                <a href={link.href} className={styles.navLink}>
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className={styles.actions}>
          <Button href={LOGIN_HREF} variant="ghost">
            Entrar
          </Button>
          <Button href={SIGNUP_HREF}>Começar agora</Button>
        </div>

        <button
          ref={toggleRef}
          type="button"
          className={styles.toggle}
          aria-expanded={menuOpen}
          aria-controls={panelId}
          aria-label={menuOpen ? 'Fechar menu' : 'Abrir menu'}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span className={styles.toggleBars} aria-hidden="true" />
        </button>
      </Container>

      <div ref={panelRef} id={panelId} className={styles.panel} hidden={!menuOpen}>
        <Container>
          <nav aria-label="Principal (móvel)">
            <ul className={styles.panelList}>
              {NAV_LINKS.map((link) => (
                <li key={link.href}>
                  <a href={link.href} className={styles.panelLink} onClick={closeMenu}>
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
          <div className={styles.panelActions}>
            <Button href={LOGIN_HREF} variant="ghost" size="lg" onClick={closeMenu}>
              Entrar
            </Button>
            <Button href={SIGNUP_HREF} size="lg" onClick={closeMenu}>
              Começar agora
            </Button>
          </div>
        </Container>
      </div>
    </header>
  );
}
