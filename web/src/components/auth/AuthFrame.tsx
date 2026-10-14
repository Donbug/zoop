import type { ReactNode } from 'react';
import './auth-entry.css';

export default function AuthFrame({
  children,
  screen,
}: {
  children: ReactNode;
  screen: string;
}) {
  return (
    <div className="auth-entry" data-screen-id={screen}>
      <header>
        <span className="auth-brand">
          줍 <small>Zoop</small>
        </span>
      </header>
      <main>{children}</main>
    </div>
  );
}
