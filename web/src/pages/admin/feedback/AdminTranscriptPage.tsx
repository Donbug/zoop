import { useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getMaskedTranscript } from '@/apis/admin/insights';
import { ApiError } from '@/apis/auth/ApiService';
import {
  Empty,
  ErrorBox,
  Loading,
  Note,
  PageHeader,
} from '@/components/admin/common/AdminUi';
import { FOCUS_RING } from '@/components/admin/common/adminStyles';
import { PurposeForm } from '@/components/admin/feedback/FeedbackReview';
import { useAsyncData } from '@/hooks/useAsyncData';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import { formatKst } from '@/util/format';

// 질문 한 건의 처리 결과(서버가 저장한 상태). 프로토타입 관리자 화면과 같은 이름을 쓴다.
const messageStatus: Record<string, string> = {
  answered: '답변함',
  insufficient_evidence: '근거 부족으로 보류',
  clarification: '되물음',
  guidance: '조건 안내',
  failed: '실패',
  cancelled: '취소',
  queued: '처리 중',
  running: '처리 중',
};

const maskedLabel: Record<string, string> = {
  email: '이메일',
  phone: '전화번호',
  rrn: '주민등록번호',
  card: '카드번호',
  account: '계좌번호',
  name: '이름',
};

function Transcript({
  sessionId,
  purpose,
}: {
  sessionId: string;
  purpose: string;
}) {
  const load = useCallback(
    () => getMaskedTranscript(sessionId, purpose),
    [sessionId, purpose],
  );
  const transcript = useAsyncData(load);
  if (transcript.status === 'loading')
    return <Loading>대화록을 불러오고 있어요</Loading>;
  if (transcript.status === 'error') {
    const error = transcript.error;
    if (error instanceof ApiError && error.status === 404)
      return <Empty>찾는 대화록이 없어요.</Empty>;
    if (error instanceof ApiError && error.code === 'MASKING_FAILED')
      return (
        <ErrorBox
          title="개인정보를 가리지 못해 대화록을 보여 주지 않았어요"
          error={error}
          onRetry={transcript.reload}
        />
      );
    if (error instanceof ApiError && error.code === 'AUDIT_UNAVAILABLE')
      return (
        <ErrorBox
          title="열람 기록을 남기지 못해 대화록을 보여 주지 않았어요"
          error={error}
          onRetry={transcript.reload}
        />
      );
    return (
      <ErrorBox
        title="대화록을 불러오지 못했어요"
        error={error}
        onRetry={transcript.reload}
      />
    );
  }
  const data = transcript.data;
  const masked = Object.entries(data.masking.counts);

  return (
    <>
      <Note>
        <span className="font-inter">{data.user}</span> ·{' '}
        {data.userKind === 'member' ? '회원' : '비회원'} · 시작{' '}
        {formatKst(data.startedAt)} · 질문 {data.messages.length}개
      </Note>
      <div
        role="note"
        className="flex flex-col gap-0.5 border-y-[0.667px] border-zoop-line py-3"
      >
        <p className="text-xs font-semibold">
          개인정보를 가린 사본이에요. 저장된 원문은 바뀌지 않았고, 이 열람은
          감사 로그에 남았어요.
        </p>
        <p className="text-[11px] text-zoop-muted">
          가리는 항목: {data.masking.rules.join(' · ')}.{' '}
          {masked.length > 0
            ? `이 대화에서 가린 것: ${masked
                .map(
                  ([kind, total]) => `${maskedLabel[kind] ?? kind} ${total}건`,
                )
                .join(' · ')}`
            : '이 대화에서는 가릴 항목이 없었어요.'}
        </p>
      </div>
      {data.messages.length === 0 ? (
        <Empty>이 대화에는 질문이 없어요.</Empty>
      ) : (
        <ol className="flex flex-col">
          {data.messages.map((message) => (
            <li
              key={message.id}
              className="flex flex-col gap-2 border-b-[0.667px] border-zoop-line py-4"
            >
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-zoop-muted">
                <span className="font-semibold text-zoop-ink">
                  질문 {message.seq}
                </span>
                <span className="font-inter tabular-nums">
                  {formatKst(message.at)}
                </span>
                <span>{messageStatus[message.status] ?? message.status}</span>
                <span>근거 인용 {message.citationCount}건</span>
              </div>
              <p className="text-[13px] font-semibold">
                <span className="sr-only">질문: </span>
                {message.question}
              </p>
              <p className="text-[13px] leading-relaxed whitespace-pre-line">
                <span className="sr-only">답변: </span>
                {message.answer}
              </p>
              {message.contextLabels.length > 0 && (
                <p className="text-[11px] text-zoop-muted">
                  연결한 대상: {message.contextLabels.join(' · ')}
                </p>
              )}
              {(message.feedback.up > 0 || message.feedback.down > 0) && (
                <div className="flex flex-col gap-1 text-[11px] text-zoop-muted">
                  <p className="tabular-nums">
                    좋아요 {message.feedback.up} · 싫어요{' '}
                    {message.feedback.down}
                  </p>
                  {message.feedback.reasons.map((reason, index) => (
                    <p key={index}>싫어요 사유: {reason}</p>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

// A-ADM-02b AI 대화록 한 건 (FS066-03, getMaskedTranscript). 열람 목적 없이는 요청하지 않는다.
export default function AdminTranscriptPage() {
  const { sessionId = '' } = useParams();
  const { params, updateQuery } = useRouteQuery();
  const purpose = params.get('purpose')?.trim() || null;
  const back = `/admin/feedback?tab=transcripts${
    purpose ? `&purpose=${encodeURIComponent(purpose)}` : ''
  }`;

  return (
    <div
      className="flex flex-col gap-5 py-8 text-zoop-ink"
      data-screen-id="A-ADM-02b"
    >
      <Link
        to={back}
        className={`self-start text-[11px] text-zoop-muted hover:text-zoop-ink ${FOCUS_RING}`}
      >
        ← AI 대화록
      </Link>
      <PageHeader title="AI 대화록" />
      {purpose ? (
        <Transcript sessionId={sessionId} purpose={purpose} />
      ) : (
        <>
          <Note>
            대화록 열람은 별도 권한이 필요하고, 열람 목적과 함께 감사 로그에
            남아요.
          </Note>
          <PurposeForm
            purpose={null}
            onSubmit={(value) =>
              updateQuery({ purpose: value }, { replace: true })
            }
          />
        </>
      )}
    </div>
  );
}
