import type { ComponentPropsWithoutRef, ElementType } from 'react';
import styles from './Container.module.css';

type ContainerProps<T extends ElementType> = { as?: T } & ComponentPropsWithoutRef<T>;

export default function Container<T extends ElementType = 'div'>({
  as,
  className = '',
  children,
  ...props
}: ContainerProps<T>) {
  const Tag: ElementType = as ?? 'div';
  return (
    <Tag className={`${styles.container} ${className}`.trim()} {...props}>
      {children}
    </Tag>
  );
}
