import { useEffect, useState } from 'react';
import { getMyFeedback } from '@/apis/feedback/feedback';
import { selectMemberId, useAuthStore } from '@/stores/useAuthStore';
import type { FeedbackFeature, FeedbackItem } from '@/types/feedback';
import FeedbackButtons from './FeedbackButtons';

type Props = {
  feature: FeedbackFeature;
  targetId: string;
  targetVersion: string;
  subject: string;
};

/** FS066 · D-AI-01b/02, D-GRP-05: restore this member's exact result version before enabling a vote. */
export default function SavedResultFeedback(props: Props) {
  const member = useAuthStore(selectMemberId);
  const revision = useAuthStore((s) => s.sessionRevision);
  if (!member) return <FeedbackButtons {...props} />;
  return (
    <LoadedFeedback
      key={`${member}:${revision}:${props.feature}:${props.targetId}:${props.targetVersion}`}
      {...props}
    />
  );
}

function LoadedFeedback(props: Props) {
  const revision = useAuthStore((s) => s.sessionRevision);
  const [saved, setSaved] = useState<FeedbackItem | null>();
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    getMyFeedback(props.feature, [props.targetId])
      .then(({ items }) => {
        if (!active || useAuthStore.getState().sessionRevision !== revision)
          return;
        const item = items.find((v) => v.targetId === props.targetId);
        if (item && item.targetVersion !== props.targetVersion)
          throw new Error('RESULT_CHANGED');
        setSaved(item ?? null);
      })
      .catch(() => {
        if (active && useAuthStore.getState().sessionRevision === revision)
          setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [props.feature, props.targetId, props.targetVersion, revision, retry]);
  if (failed)
    return (
      <p role="alert" className="text-xs text-zoop-muted">
        내 평가를 불러오지 못했어요.{' '}
        <button
          type="button"
          className="underline"
          onClick={() => {
            setFailed(false);
            setSaved(undefined);
            setRetry((n) => n + 1);
          }}
        >
          다시 시도
        </button>
      </p>
    );
  if (saved === undefined)
    return (
      <p role="status" className="text-xs text-zoop-muted">
        내 평가를 확인하고 있어요.
      </p>
    );
  return (
    <FeedbackButtons
      {...props}
      saved={saved?.value ?? 'none'}
      savedReason={saved?.reason ?? null}
      onSaved={setSaved}
    />
  );
}
