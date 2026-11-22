import { Inter, JetBrains_Mono } from 'next/font/google';
import './globals.css';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-sans',
  display: 'swap',
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
});

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'http://localhost:3000';
const TITLE = 'Vollab — Plataforma de apoio para traders de opções';
const DESCRIPTION =
  'Superfície de volatilidade, gregas, simulação de estratégias e gestão de risco em um só lugar para quem opera opções.';

export const metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: TITLE,
    template: '%s · Vollab',
  },
  description: DESCRIPTION,
  applicationName: 'Vollab',
  alternates: { canonical: '/' },
  icons: {
    // Segue o tema do sistema (não o do site).
    icon: [
      { url: '/logo/v-preto.svg', type: 'image/svg+xml', media: '(prefers-color-scheme: light)' },
      { url: '/logo/v-branco.svg', type: 'image/svg+xml', media: '(prefers-color-scheme: dark)' },
      // Fallback para navegadores que ignoram `media` (ex.: Safari): o SVG troca a cor sozinho.
      { url: '/favicon.svg', type: 'image/svg+xml' },
    ],
    // Declarado aqui porque `icons` substitui a detecção automática de app/apple-icon.png.
    apple: [{ url: '/apple-icon.png', sizes: '180x180', type: 'image/png' }],
  },
  openGraph: {
    type: 'website',
    locale: 'pt_BR',
    url: '/',
    siteName: 'Vollab',
    title: TITLE,
    description: DESCRIPTION,
    images: [{ url: '/og.png', width: 1200, height: 630, alt: 'Vollab — Plataforma de apoio para traders de opções' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: TITLE,
    description: DESCRIPTION,
    images: ['/og.png'],
  },
};

export const viewport = {
  themeColor: '#0D0D12',
  colorScheme: 'dark',
};

export default function RootLayout({ children }) {
  return (
    <html lang="pt-BR" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
