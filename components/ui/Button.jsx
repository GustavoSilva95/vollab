import Link from 'next/link';
import styles from './Button.module.css';

/**
 * Link com aparência de botão (todas as ações da home são navegação).
 * variant: 'primary' | 'ghost' · size: 'md' | 'lg'
 */
export default function Button({ href, variant = 'primary', size = 'md', className = '', children, ...props }) {
  const classes = [styles.button, styles[variant], styles[size], className].filter(Boolean).join(' ');
  return (
    <Link href={href} className={classes} {...props}>
      {children}
    </Link>
  );
}
