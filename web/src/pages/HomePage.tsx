import { Link } from 'react-router-dom';

export default function HomePage() {
  return (
    <section className="py-8 md:py-12">
      <p className="text-sm font-semibold text-emerald-600">오늘의 브리핑</p>
      <h1 className="mt-2 text-3xl font-bold tracking-tight text-gray-950 md:text-4xl">
        시장의 연결을 한눈에 확인하세요
      </h1>
      <p className="mt-4 max-w-2xl leading-7 text-gray-600">
        이 화면은 Zoop 기능이 채워질 자리와 공통 레이아웃을 확인하기 위한 초기
        페이지입니다.
      </p>

      <div className="mt-8 grid gap-4 md:grid-cols-3">
        {['브리핑', '관계 그래프', '내 종목'].map((title, index) => (
          <article
            key={title}
            className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm"
          >
            <p className="text-xs font-semibold text-gray-400">0{index + 1}</p>
            <h2 className="mt-6 text-xl font-semibold text-gray-950">
              {title}
            </h2>
            <p className="mt-2 text-sm leading-6 text-gray-500">
              기능 API와 디자인이 확정되면 이 영역에 실제 콘텐츠를 연결합니다.
            </p>
          </article>
        ))}
      </div>

      <Link
        to="/detail/example"
        className="mt-8 inline-flex rounded-xl bg-emerald-600 px-5 py-3 font-semibold text-white hover:bg-emerald-700"
      >
        상세 라우트 확인
      </Link>
    </section>
  );
}
