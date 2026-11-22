import styles from './SectionTitle.module.css';

export default function SectionTitle({ id, eyebrow, title, description, align = 'left' }) {
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
