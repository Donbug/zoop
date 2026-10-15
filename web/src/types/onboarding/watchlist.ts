// D-WAT-01/01b consumer types from docs/api/openapi.yaml; responses are not wrapped in data.
export interface WatchlistCompany {
  id: string;
  name: string;
  ticker: string | null;
  aliases: string[];
  sector: string | null;
  brandColor: string | null;
  logoUrl: string | null;
  issueCount: number;
}
export interface InitialSettings {
  mode: 'assets' | 'watchlist' | null;
  watchlistIds: string[];
  tutorialCompleted: boolean;
  completed: boolean;
  investor: boolean | null;
  version: number;
}
export interface InitialPortfolio {
  connected: boolean;
  holdings: { companyId: string; name: string; ticker: string | null }[];
}
export interface CompleteInitialSettings {
  version: number;
  mode: 'assets' | 'watchlist';
  watchlistIds: string[];
  completed: true;
  investor?: boolean;
}
