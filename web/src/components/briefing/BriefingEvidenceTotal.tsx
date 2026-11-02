import type { BriefingItem } from '@/types/briefing';
import { NOTE } from './briefingStyles';

/** D-BRF-01·02 B1: 이 목록의 근거 ID 합집합만 세고, 없는 근거는 만들지 않는다. */
export default function BriefingEvidenceTotal({
  items,
}: {
  items?: BriefingItem[];
}) {
  const count = new Set(items?.flatMap((item) => item.evidenceIds)).size;
  return count > 0 ? (
    <p className={`${NOTE} mt-4 border-t border-zoop-border pt-3 tabular-nums`}>
      근거 문서 {count}건
    </p>
  ) : null;
}
