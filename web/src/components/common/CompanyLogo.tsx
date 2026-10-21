import { useState } from 'react';

type CompanyLogoProps = {
  name: string;
  logoUrl?: string | null;
  /** 원형 틀의 크기·색. 로고가 없을 때 보이는 첫 글자 표식도 이 틀을 쓴다. */
  className: string;
};

/** 기업 로고. 로고가 없거나 불러오지 못하면 이름 첫 글자를 보인다. */
export default function CompanyLogo({
  name,
  logoUrl,
  className,
}: CompanyLogoProps) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const showLogo = Boolean(logoUrl) && failedUrl !== logoUrl;
  return (
    <span
      aria-hidden="true"
      className={`grid shrink-0 place-items-center overflow-hidden ${className}`}
    >
      {showLogo ? (
        <img
          src={logoUrl!}
          alt=""
          className="size-full object-cover"
          onError={() => setFailedUrl(logoUrl!)}
        />
      ) : (
        name.slice(0, 1)
      )}
    </span>
  );
}
