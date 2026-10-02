// 실제 앱(App.tsx: 실제 라우트·가드·QueryClient 설정·화면)을 jsdom에 올리고, 네트워크만 BFF 대역으로 바꾼다.
// 시험마다 모듈을 새로 불러 QueryClient·라우터가 이전 시험의 상태를 물려받지 않는다.
import { act, cleanup, render } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { afterEach, expect, vi } from "vitest";
import { FakeBff } from "./fake-bff";
import { World } from "./fixtures";
import { sleep } from "./time";

export interface Harness<T = undefined> {
  bff: FakeBff;
  world: World;
  user: UserEvent;
  /** `setup`이 돌려준 값(붙잡아 둔 요청 등) */
  held: T;
  /** 주소창에 새 주소를 넣은 것과 같다(브라우저 앞/뒤로 이동). */
  navigate: (path: string) => Promise<void>;
  /** 응답이 모두 오가고 화면이 반영될 때까지 기다린다. "아무 일도 일어나지 않았음"을 확인하기 전에 쓴다. */
  settle: () => Promise<void>;
}

let open: FakeBff | null = null;

afterEach(() => {
  // 화면을 먼저 내려야 내려가는 중 부르는 취소 등이 요청 대역에 닿는다.
  cleanup();
  const unhandled = open?.unhandled ?? [];
  open = null;
  vi.unstubAllGlobals();
  // 시험이 정의하지 않은 요청을 앱이 보냈다면 시험 세계가 앱을 못 따라간 것이다. 조용히 넘기지 않는다.
  expect(unhandled, "fake BFF에 정의되지 않은 요청").toEqual([]);
});

/** `setup`은 앱이 뜨기 전에 불린다: 붙잡을 요청(hold)이나 덮어쓸 응답을 여기서 정하고, 돌려준 값은 `held`로 받는다. */
export async function openApp<T = undefined>(path: string, setup?: (bff: FakeBff, world: World) => T): Promise<Harness<T>> {
  vi.resetModules();
  const bff = new FakeBff();
  const world = new World();
  world.serve(bff);
  const held = setup?.(bff, world) as T;
  bff.install();
  open = bff;

  window.history.replaceState(null, "", path);
  // 정적 import로는 안 된다: App.tsx가 모듈 최상위에서 QueryClient·라우터를 만들므로, 시험마다 새로 평가해야 서로의 캐시·이력을 물려받지 않는다.
  const { App } = await import("@/App");
  const user = userEvent.setup();
  render(<App />);

  const settle = async () => {
    for (let round = 0; round < 2; round += 1) {
      await bff.idle();
      await act(async () => {
        await sleep(30);
      });
    }
  };
  const navigate = async (next: string) => {
    await act(async () => {
      window.history.pushState(null, "", next);
      window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
    });
  };
  return { bff, world, user, held, navigate, settle };
}
