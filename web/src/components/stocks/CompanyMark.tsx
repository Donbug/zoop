import CompanyLogo from '@/components/common/CompanyLogo';

/** 기업 원형 표식(D-MY-01 화면 명세). 로고가 없으면 이름 첫 글자를 보인다. */
export default function CompanyMark({
  name,
  logoUrl,
}: {
  name: string;
  logoUrl?: string | null;
}) {
  return (
    <CompanyLogo
      name={name}
      logoUrl={logoUrl}
      className="size-8 rounded-full bg-gray-200 text-sm font-semibold text-zoop-ink"
    />
  );
}
