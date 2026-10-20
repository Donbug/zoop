import { Link } from 'react-router-dom';
import './service-shell.css';

// D-AUT-01/02 · D-ONB-01/02 · D-WAT-01/01b, Figma 619:1087.
export default function SlimHeader() {
  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-zoop-line bg-white px-5 text-zoop-ink">
      <Link
        to="/"
        aria-label="줍 Zoop"
        className="flex items-center gap-1.5 no-underline focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        <strong className="text-base font-extrabold">줍</strong>
        <span className="font-inter text-[11px] text-zoop-muted">Zoop</span>
      </Link>
      <div
        aria-label="화면 도구"
        className="flex items-center gap-2 text-zoop-muted"
      >
        <span className="grid size-8 place-items-center" aria-hidden="true">
          <img
            src="/graph-assets/slim-archive.svg"
            width="16"
            height="16"
            alt=""
          />
        </span>
        <span className="grid size-8 place-items-center" aria-hidden="true">
          <img
            src="/graph-assets/slim-moon.svg"
            width="16"
            height="16"
            alt=""
          />
        </span>
        <span className="grid size-8 place-items-center" aria-hidden="true">
          <img
            src="/graph-assets/slim-user.svg"
            width="16"
            height="16"
            alt=""
          />
        </span>
      </div>
    </header>
  );
}
