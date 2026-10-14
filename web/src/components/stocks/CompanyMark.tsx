/** 기업 이름 첫 글자 표시(D-MY-01 화면 명세의 원형 표식). 로고 계약이 정해지기 전까지 쓴다. */
export default function CompanyMark({ name }: { name: string }) {
  return (
    <span
      aria-hidden="true"
      className="flex size-8 shrink-0 items-center justify-center rounded-full bg-gray-200 text-sm font-semibold text-gray-700"
    >
      {name.slice(0, 1)}
    </span>
  );
}
