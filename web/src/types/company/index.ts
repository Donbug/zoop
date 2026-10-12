export type CompanyTab = 'events' | 'documents' | 'info';

export type CompanyTabOption = {
  value: CompanyTab;
  label: string;
};

export type ChartPeriod = '1d' | '1w' | '1m' | '1y' | 'all';
