import { useLocation } from 'react-router-dom';

const labels: Record<string, string> = {
  '/stocks': '종목',
  '/companies': '종목',
  '/briefing': '브리핑',
  '/my': '내 종목',
};

export default function OutOfScopePage() {
  const { pathname } = useLocation();
  return (
    <section className="out-of-scope-page" aria-labelledby="out-of-scope-title">
      <h1 id="out-of-scope-title">{labels[pathname] ?? '화면'}</h1>
      <p>현재 담당 구현 범위에 포함되지 않은 화면입니다.</p>
    </section>
  );
}
