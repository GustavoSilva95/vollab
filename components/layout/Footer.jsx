import Container from '@/components/ui/Container';
import { LOGIN_HREF, NAV_LINKS, SIGNUP_HREF } from './navLinks';
import styles from './Footer.module.css';

// Placeholder: trocar pelo e-mail definitivo.
const CONTACT_EMAIL = 'contato@vollab.com.br';
const TAGLINE = 'Plataforma de apoio para traders de opções';

const LINK_GROUPS = [
  { title: 'Produto', links: NAV_LINKS.filter((link) => link.href !== '#contato') },
  {
    title: 'Conta',
    links: [
      { href: LOGIN_HREF, label: 'Entrar' },
      { href: SIGNUP_HREF, label: 'Criar conta' },
    ],
  },
  { title: 'Contato', links: [{ href: `mailto:${CONTACT_EMAIL}`, label: CONTACT_EMAIL }] },
];

export default function Footer() {
  const year = new Date().getFullYear();

  return (
    <footer id="contato" className={styles.footer}>
      <Container>
        <div className={styles.top}>
          <div className={styles.brand}>
            {/* A versão com frase só é legível a partir de ~480px; abaixo, logo simples + frase em HTML. */}
            <picture>
              <source
                media="(min-width: 480px)"
                srcSet="/logo/logo-com-frase-fundo-escuro.svg"
                width={5752}
                height={975}
              />
              <img
                src="/logo/logo-fundo-escuro.svg"
                alt="Vollab"
                width={2504}
                height={975}
                decoding="async"
                className={styles.logo}
              />
            </picture>
            <p className={styles.tagline}>{TAGLINE}</p>
          </div>

          <nav className={styles.groups} aria-label="Rodapé">
            {LINK_GROUPS.map((group) => (
              <div key={group.title}>
                <h2 className={`${styles.groupTitle} mono`}>{group.title}</h2>
                <ul className={styles.list}>
                  {group.links.map((link) => (
                    <li key={link.href}>
                      <a href={link.href} className={styles.link}>
                        {link.label}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </div>

        <div className={styles.bottom}>
          <p className={styles.disclaimer}>
            Conteúdo informativo; não constitui recomendação de investimento. Operações com opções envolvem
            riscos e podem resultar em perdas superiores ao capital investido.
          </p>
          <p className={styles.copy}>© {year} Vollab. Todos os direitos reservados.</p>
        </div>
      </Container>
    </footer>
  );
}
