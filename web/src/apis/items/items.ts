import { call } from '@/apis/auth/ApiService';
import type { ApiResponse, PageResponse } from '@/apis/commonType';
import type { CreateItemRequest, Item, ItemListParams } from '@/types/stocks';

const ITEMS_BASE = '/api/v1/items';

function toQueryString(params: ItemListParams) {
  const search = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  });

  const query = search.toString();
  return query ? `?${query}` : '';
}

export async function getItems(
  params: ItemListParams = {},
): Promise<PageResponse<Item>> {
  const response = await call<ApiResponse<PageResponse<Item>>>(
    `${ITEMS_BASE}${toQueryString(params)}`,
    'GET',
  );

  return response.data;
}

export async function createItem(request: CreateItemRequest): Promise<Item> {
  const response = await call<ApiResponse<Item>>(ITEMS_BASE, 'POST', request);

  return response.data;
}
