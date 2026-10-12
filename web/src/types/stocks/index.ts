export type Item = {
  id: number;
  title: string;
  createdAt: string;
};

export type ItemListParams = {
  page?: number;
  size?: number;
  keyword?: string;
};

export type CreateItemRequest = {
  title: string;
};
