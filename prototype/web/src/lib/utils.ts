import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** 조건부 클래스 이름을 합치고, 충돌하는 Tailwind 클래스는 뒤의 것을 남긴다. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** 긴 문장을 그래프 라벨 등에 넣을 때 글자 수로 자른다. */
export function truncate(text: string, max: number) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
