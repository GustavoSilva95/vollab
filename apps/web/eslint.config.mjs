import { defineConfig, globalIgnores } from 'eslint/config';
import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTs from 'eslint-config-next/typescript';

/**
 * PRD-UI-03: a formatação de números, datas e unidades fica num módulo único
 * (`lib/format`). Fora dele, componentes não formatam número por conta própria.
 */
const FORMAT_ONLY_IN_LIB =
  'Formatação de número, data ou unidade só em lib/format (PRD-UI-03). Importe a função de lá.';

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: ['**/*.{ts,tsx}'],
    ignores: ['lib/format/**'],
    rules: {
      'no-restricted-properties': [
        'error',
        { property: 'toFixed', message: FORMAT_ONLY_IN_LIB },
        { property: 'toPrecision', message: FORMAT_ONLY_IN_LIB },
        { property: 'toLocaleString', message: FORMAT_ONLY_IN_LIB },
        { property: 'toLocaleDateString', message: FORMAT_ONLY_IN_LIB },
        { property: 'toLocaleTimeString', message: FORMAT_ONLY_IN_LIB },
        { object: 'Intl', property: 'NumberFormat', message: FORMAT_ONLY_IN_LIB },
        { object: 'Intl', property: 'DateTimeFormat', message: FORMAT_ONLY_IN_LIB },
      ],
    },
  },
  globalIgnores([
    '.next/**',
    'out/**',
    'build/**',
    'next-env.d.ts',
    'playwright-report/**',
    'test-results/**',
  ]),
]);

export default eslintConfig;
