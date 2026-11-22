import ComingSoon from '@/components/sections/ComingSoon';

export const metadata = {
  title: 'Criar conta',
  robots: { index: false },
};

export default function SignupPage() {
  return (
    <ComingSoon
      title="Cadastro"
      description="Estamos preparando a abertura de contas. Em breve você poderá se cadastrar por aqui."
    />
  );
}
