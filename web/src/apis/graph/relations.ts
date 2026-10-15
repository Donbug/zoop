import {
  createMockRelation,
  type RelationMockScenario,
} from '@/mocks/relations/fixture';
import type { EventContext } from '@/types/map/event';

// WBS 6.6.24 is mock-only, including production builds. No HTTP fallback.
export async function getRelation(id: string, context: EventContext = {}) {
  await new Promise((resolve) => setTimeout(resolve, 220));
  return createMockRelation(
    id,
    context,
    import.meta.env.VITE_RELATION_MOCK_SCENARIO as
      RelationMockScenario | undefined,
  );
}
