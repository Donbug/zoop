import type { IssueFollowUps } from './issueFollowUps';

export type FollowUpReviewEntry = {
  ref: Pick<
    IssueFollowUps['entries'][number],
    'issueId' | 'companyId' | 'origin' | 'condition'
  >;
  status: 'fulfilled' | 'insufficient_evidence';
  summary: string;
  facts: { text: string; sourceIds: string[] }[];
  requirements: {
    text: string;
    observation: 'unverified' | 'completed';
    sourceIds: string[];
  }[];
  sources: {
    id: string;
    documentId: string;
    bodySha256: string;
    title: string;
    url: string;
    publishedAt: string;
    quote: string;
    start: number;
    end: number;
    relation: 'same_event' | 'related_event';
    kind: 'plan' | 'completed_action' | 'background';
    period: 'after_condition' | 'prior_background';
  }[];
};

export type IssueFollowUpReview = {
  schemaVersion: 'issue-followup-review-v1';
  method: 'recorded_editorial_review';
  roundId: string;
  baseResultVersion: string;
  cutoff: string;
  reviewedAt: string;
  entries: FollowUpReviewEntry[];
};
