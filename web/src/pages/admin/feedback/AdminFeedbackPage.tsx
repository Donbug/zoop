import { PageHeader, Segmented, Tabs } from '@/components/admin/common/AdminUi';
import {
  DateRangeForm,
  DislikesPanel,
  FeedbackSummaryPanel,
  TranscriptsPanel,
} from '@/components/admin/feedback/FeedbackReview';
import {
  parseWindow,
  windowOptions,
} from '@/components/admin/stats/statsWindow';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import type { FeedbackPeriod } from '@/types/admin/insights';

const TABS = ['summary', 'dislikes', 'transcripts'] as const;
type FeedbackTab = (typeof TABS)[number];

const isDay = (value: string | null) =>
  value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null;

// A-ADM-02b 선호도·대화록 (FS066-02·FS066-03)
// - 현재 유효한 평가만 세고, 기간은 평가를 마지막으로 바꾼 시각(KST)으로 거른다. 기본은 전체 보관 기간이다.
// - 기간·날짜·탭·대화록 보기는 주소에 남는다.
export default function AdminFeedbackPage() {
  const { params, updateQuery } = useRouteQuery();
  const period: FeedbackPeriod = {
    window: parseWindow(params.get('window'), 'all'),
    start: isDay(params.get('start')),
    end: isDay(params.get('end')),
  };
  const rawTab = params.get('tab') as FeedbackTab | null;
  const tab: FeedbackTab = rawTab && TABS.includes(rawTab) ? rawTab : 'summary';
  const only = params.get('only') === 'disliked' ? 'disliked' : 'all';
  const purpose = params.get('purpose')?.trim() || null;
  const update = (changes: Record<string, string | null>) =>
    updateQuery(changes, { replace: true });

  return (
    <div
      className="flex flex-col gap-5 py-8 text-zoop-ink"
      data-screen-id="A-ADM-02b"
    >
      <PageHeader
        title="선호도"
        actions={
          tab === 'transcripts' ? undefined : (
            <Segmented
              label="집계 기간"
              value={period.window}
              options={windowOptions}
              onChange={(value) =>
                update({
                  window: value === 'all' ? null : value,
                  start: null,
                  end: null,
                })
              }
            />
          )
        }
      />
      <Tabs
        label="선호도 보기"
        value={tab}
        options={[
          { value: 'summary', label: '요약' },
          { value: 'dislikes', label: '싫어요 사유' },
          { value: 'transcripts', label: 'AI 대화록' },
        ]}
        onChange={(value) =>
          update({ tab: value === 'summary' ? null : value })
        }
      />
      <div role="tabpanel" className="flex flex-col gap-5">
        {tab !== 'transcripts' && (
          <DateRangeForm
            key={`${period.start}-${period.end}`}
            start={period.start}
            end={period.end}
            onApply={(start, end) => update({ start, end })}
          />
        )}
        {tab === 'summary' && <FeedbackSummaryPanel period={period} />}
        {tab === 'dislikes' && (
          <DislikesPanel period={period} purpose={purpose} />
        )}
        {tab === 'transcripts' && (
          <TranscriptsPanel
            only={only}
            purpose={purpose}
            onOnlyChange={(value) =>
              update({ only: value === 'all' ? null : value })
            }
            onPurposeChange={(value) => update({ purpose: value })}
          />
        )}
      </div>
    </div>
  );
}
