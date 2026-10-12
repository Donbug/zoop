import { Link, useParams } from 'react-router-dom';

export default function DetailPage() {
  const { id } = useParams();

  return (
    <main className="min-h-dvh bg-white px-4 py-8 md:px-8 md:py-12">
      <div className="mx-auto max-w-3xl">
        <Link to="/home" className="text-sm font-semibold text-emerald-700">
          ← 홈으로
        </Link>
        <p className="mt-10 text-sm text-gray-400">상세 ID: {id}</p>
        <h1 className="mt-2 text-3xl font-bold text-gray-950">상세 페이지</h1>
        <p className="mt-4 leading-7 text-gray-600">
          공통 내비게이션 없이 표시되는 보호 라우트의 초기 예시입니다.
        </p>
      </div>
    </main>
  );
}
