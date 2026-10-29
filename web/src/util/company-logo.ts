// D-GRP-01/03: published snapshots may omit logos; reuse checked-in brand assets by company ID.
const logos: Record<string, string> = {
  'KRX:005930': 'samsung.svg',
  'KRX:006400': 'samsung.svg',
  'KRX:000660': 'sk-hynix.svg',
  'KRX:042700': 'hanmi-semiconductor.svg',
  'KRX:035420': 'naver.svg',
  'KRX:035720': 'kakao.svg',
  'KRX:030200': 'kt.svg',
  'KRX:005380': 'hyundai.svg',
  'NASDAQ:NVDA': 'nvidia.svg',
  'NASDAQ:AMD': 'amd.svg',
  'NASDAQ:ASML': 'asml.svg',
  'NYSE:TSM': 'tsmc.svg',
  'NASDAQ:AAPL': 'apple.svg',
  'NASDAQ:GOOGL': 'alphabet.svg',
  'NASDAQ:META': 'meta.svg',
  'NASDAQ:INTC': 'intel.svg',
  'NASDAQ:AVGO': 'broadcom.svg',
  'NASDAQ:QCOM': 'qualcomm.svg',
  'NASDAQ:ARM': 'arm.svg',
  'NASDAQ:TSLA': 'tesla.svg',
  'ORG:OPENAI': 'openai.svg',
  'ORG:ANTHROPIC': 'anthropic.svg',
  'NASDAQ:MU': 'micron.svg',
  'NASDAQ:MSFT': 'microsoft.svg',
  'NASDAQ:AMZN': 'amazon.svg',
  'KRX:064400': 'lg.svg',
  'KRX:018260': 'samsung-sds.svg',
  'KRX:000990': 'db-hitek.svg',
  'KRX:017670': 'sk-telecom.svg',
};

// These checked-in square marks already include a background and safe artwork margins.
// Other marks fit in the inscribed square so circular nodes cannot cut their corners off.
export function logoScale(url?: string | null) {
  return url &&
    [
      'samsung',
      'samsung-sds',
      'sk-hynix',
      'sk-telecom',
      'asml',
      'naver',
      'kakao',
      'kt',
    ].some((name) => url === `/graph-assets/${name}.svg`)
    ? 1
    : 0.68;
}

// Sampled from the checked-in logos, filling the circle without enlarging/cropping the mark.
export function logoBackground(url?: string | null) {
  if (url === '/graph-assets/micron.svg') return '#000000';
  if (url === '/graph-assets/amazon.svg') return '#232f3e';
  return '#ffffff';
}

export function companyLogo(
  id: string,
  supplied?: string | null,
): string | null {
  // User-supplied replacements take precedence over older snapshot URLs.
  if (
    [
      'KRX:006400',
      'KRX:035420',
      'KRX:035720',
      'KRX:030200',
      'NASDAQ:GOOGL',
    ].includes(id)
  )
    return `/graph-assets/${logos[id]}`;
  return supplied || (logos[id] ? `/graph-assets/${logos[id]}` : null);
}
