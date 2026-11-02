import { Link, isRouteErrorResponse, useRouteError } from 'react-router-dom';

// FS001: preserve a usable route when a page cannot be displayed.
export default function RouteError({
  notFound = false,
}: {
  notFound?: boolean;
}) {
  const error = useRouteError();
  const missing =
    notFound || (isRouteErrorResponse(error) && error.status === 404);
  return (
    <main className="mx-auto max-w-lg p-8 text-zoop-ink">
      <h1 className="text-title font-bold">
        {missing ? '페이지를 찾을 수 없어요' : '화면을 불러오지 못했어요'}
      </h1>
      <p className="mt-3 text-body text-zoop-muted">
        {missing
          ? '주소를 확인하거나 지도로 돌아가 주세요.'
          : '다시 시도하거나 지도로 돌아가 주세요.'}
      </p>
      {!missing && (
        <button
          type="button"
          className="mt-5 mr-4 underline"
          onClick={() => window.location.reload()}
        >
          다시 시도
        </button>
      )}
      <Link
        className="mt-5 inline-block underline max-md:min-h-10 max-md:content-center"
        to="/"
      >
        지도로 돌아가기
      </Link>
    </main>
  );
}
