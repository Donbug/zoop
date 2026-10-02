/** 실제 시간으로 ms만큼 기다린다. 응답 대역과 화면 반영을 기다리는 곳에서 함께 쓴다. */
export function sleep(ms: number) {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, ms);
  return promise;
}
