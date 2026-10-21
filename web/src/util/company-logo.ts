// D-GRP-01/03: published snapshots may omit logos; reuse checked-in brand assets by company ID.
const logos: Record<string, string> = {
  'KRX:005930': 'samsung.svg',
  'KRX:000660': 'sk-hynix.svg',
  'KRX:042700': 'hanmi-semiconductor.svg',
  'KRX:035420': 'naver.svg',
  'KRX:035720': 'kakao.svg',
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

export function companyLogo(
  id: string,
  supplied?: string | null,
): string | null {
  return supplied || (logos[id] ? `/graph-assets/${logos[id]}` : null);
}
