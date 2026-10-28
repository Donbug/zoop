// 소셜 계정 연결에서 돌아온 결과(?social=). 결과 값만 옮기고 OAuth 자격 증명은 다루지 않는다.
export type SocialLinkResult = 'linked' | 'cancelled' | 'failed';

export function readSocialLinkResult(search: string): SocialLinkResult | null {
  const value = new URLSearchParams(search).get('social');
  return value === 'linked' || value === 'cancelled' || value === 'failed'
    ? value
    : null;
}

export const socialLinkMessage: Record<SocialLinkResult, string> = {
  linked: '소셜 계정을 연결했어요.',
  cancelled: '계정 연결을 취소했어요.',
  failed: '계정을 연결하지 못했어요. 다시 시도해 주세요.',
};
