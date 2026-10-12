export default function SearchPage() {
  return (
    <section className="py-8 md:py-12">
      <h1 className="text-3xl font-bold text-gray-950">탐색</h1>
      <p className="mt-3 text-gray-600">
        기업, 이슈, 관계를 탐색하는 기능이 들어갈 페이지입니다.
      </p>
      <label className="mt-8 block max-w-2xl">
        <span className="sr-only">검색어</span>
        <input
          type="search"
          placeholder="기업 또는 이슈를 검색해 보세요"
          className="w-full rounded-2xl border border-gray-300 bg-white px-5 py-4 outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-100"
        />
      </label>
    </section>
  );
}
