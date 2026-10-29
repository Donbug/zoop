// 80번 본문 건너뛰기. 주소에 #이 남지 않게 기본 이동을 막고 본문(<main id tabIndex={-1}>)으로 포커스만 옮긴다.
export default function SkipLink() {
  return (
    <a
      href="#service-main"
      onClick={(event) => {
        event.preventDefault();
        document.getElementById('service-main')?.focus();
      }}
      className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:bg-zoop-paper focus:p-3"
    >
      본문으로 건너뛰기
    </a>
  );
}
