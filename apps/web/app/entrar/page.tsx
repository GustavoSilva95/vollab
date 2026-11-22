import { redirect } from 'next/navigation';

/** Sem login na fase 1: `/entrar` leva direto ao cockpit (ADR-13). */
export default function LoginPage() {
  redirect('/app');
}
