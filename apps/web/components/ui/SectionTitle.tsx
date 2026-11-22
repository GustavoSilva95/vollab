import styles from './SectionTitle.module.css';

interface SectionTitleProps {
  id: string;
  eyebrow?: string;
  title: string;
  description?: string;
  align?: 'left' | 'center';
}

export default function SectionTitle({ id, eyebrow, title, description, align = 'left' }: SectionTitleProps) {
  return (
    <header className={`${styles.header} ${align === 'center' ? styles.center : ''}`}>
      {eyebrow && <p className={`${styles.eyebrow} mono`}>{eyebrow}</p>}
      <h2 id={id} className={styles.title}>
        {title}
      </h2>
      {description && <p className={styles.description}>{description}</p>}
    </header>
  );
}
