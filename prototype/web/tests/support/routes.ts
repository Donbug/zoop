// 앱 주소와 BFF 경로를 시험에서 같은 방식으로 쓰기 위한 도우미.
import type { Period } from "@/lib/company-timeline";
import type { RecordedRequest, Where } from "./fake-bff";
import { periodOfRange, type TestCompany } from "./fixtures";

const idOf = (c: TestCompany) => encodeURIComponent(c.id);

/** 브라우저 주소 */
export const pageOf = (c: TestCompany, query = "") => `/companies/${idOf(c)}${query}`;

/** BFF 경로 */
export const endpoint = {
  company: (c: TestCompany) => `/api/companies/${idOf(c)}`,
  quote: (c: TestCompany) => `/api/companies/${idOf(c)}/quote`,
  metrics: (c: TestCompany) => `/api/companies/${idOf(c)}/metrics`,
  prices: (c: TestCompany) => `/api/companies/${idOf(c)}/prices`,
  documents: (c: TestCompany) => `/api/companies/${idOf(c)}/documents`,
  events: "/api/events",
};

/** 사건 목록 요청 중 기업 c, 기간 period의 것 */
export const eventsOf =
  (c: TestCompany, period: Period): Where =>
  (r: RecordedRequest) =>
    r.query.get("companyId") === c.id && periodOfRange(r.query.get("from")!, r.query.get("to")!) === period;

/** 시세 차트 요청 중 기간 period의 것 */
export const pricesInPeriod =
  (period: Period): Where =>
  (r: RecordedRequest) =>
    r.query.get("period") === period;
