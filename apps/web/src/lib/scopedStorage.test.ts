import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { TOKEN_KEY } from "./auth";
import {
  SESSION_ID_KEY,
  clearAllScopedKeys,
  clearScoped,
  promoteScopedKeys,
  readScoped,
  writeScoped,
} from "./scopedStorage";

/**
 * 로그인 여부에 따른 저장 위치 분리 테스트.
 *
 * 지키려는 규칙은 하나다 — 비로그인 사용자가 입력한 값은 탭을 닫으면 사라져야
 * 하고(sessionStorage), 로그인 사용자의 값은 다음 방문까지 남아야 한다
 * (localStorage). 예전에는 무조건 localStorage 라서 비로그인 가족정보가
 * 브라우저를 닫았다 열어도 그대로 복원됐다.
 *
 * vitest 환경이 node 라 window 가 없다. 최소한의 Storage 구현을 심어서
 * "탭을 닫는다"(sessionStorage 만 비움)를 흉내낸다.
 */

class FakeStorage implements Storage {
  private data = new Map<string, string>();

  get length(): number {
    return this.data.size;
  }

  clear(): void {
    this.data.clear();
  }

  getItem(key: string): string | null {
    return this.data.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.data.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.data.delete(key);
  }

  setItem(key: string, value: string): void {
    this.data.set(key, value);
  }
}

let localStore: FakeStorage;
let sessionStore: FakeStorage;

function signIn(): void {
  localStore.setItem(TOKEN_KEY, "fake-token");
}

/** 탭을 닫았다가 다시 여는 상황. sessionStorage 만 비워진다. */
function closeTab(): void {
  sessionStore.clear();
}

beforeEach(() => {
  localStore = new FakeStorage();
  sessionStore = new FakeStorage();
  (globalThis as { window?: unknown }).window = {
    localStorage: localStore,
    sessionStorage: sessionStore,
  };
});

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
});

describe("비로그인", () => {
  it("값을 sessionStorage 에만 쓴다", () => {
    writeScoped(SESSION_ID_KEY, "s-1");

    expect(sessionStore.getItem(SESSION_ID_KEY)).toBe("s-1");
    expect(localStore.getItem(SESSION_ID_KEY)).toBeNull();
  });

  it("탭을 닫으면 값이 사라진다", () => {
    writeScoped(SESSION_ID_KEY, "s-1");
    expect(readScoped(SESSION_ID_KEY)).toBe("s-1");

    closeTab();

    expect(readScoped(SESSION_ID_KEY)).toBeNull();
  });

  it("새로고침(탭 유지)은 견딘다", () => {
    writeScoped(SESSION_ID_KEY, "s-1");

    // 새로고침은 sessionStorage 를 비우지 않는다.
    expect(readScoped(SESSION_ID_KEY)).toBe("s-1");
  });
});

describe("로그인", () => {
  it("값을 localStorage 에 써서 다음 방문까지 남긴다", () => {
    signIn();

    writeScoped(SESSION_ID_KEY, "s-1");
    closeTab();

    expect(readScoped(SESSION_ID_KEY)).toBe("s-1");
  });

  it("반대쪽 저장소에 남은 값을 지워 둘이 어긋나지 않게 한다", () => {
    writeScoped(SESSION_ID_KEY, "anon");
    signIn();

    writeScoped(SESSION_ID_KEY, "owned");

    expect(sessionStore.getItem(SESSION_ID_KEY)).toBeNull();
    expect(localStore.getItem(SESSION_ID_KEY)).toBe("owned");
  });
});

describe("로그인 승격", () => {
  it("비로그인으로 쓰던 값을 계정 저장소로 옮긴다", () => {
    writeScoped(SESSION_ID_KEY, "s-1");
    writeScoped("nlp1.family_graph_id", "g-1");

    signIn();
    promoteScopedKeys();

    expect(localStore.getItem(SESSION_ID_KEY)).toBe("s-1");
    expect(localStore.getItem("nlp1.family_graph_id")).toBe("g-1");
    expect(sessionStore.getItem(SESSION_ID_KEY)).toBeNull();

    closeTab();
    expect(readScoped(SESSION_ID_KEY)).toBe("s-1");
  });

  it("옮길 값이 없으면 아무 것도 만들지 않는다", () => {
    signIn();
    promoteScopedKeys();

    expect(localStore.getItem(SESSION_ID_KEY)).toBeNull();
  });
});

describe("정리", () => {
  it("로그아웃 시 양쪽 저장소에서 모두 지운다", () => {
    signIn();
    writeScoped(SESSION_ID_KEY, "owned");
    sessionStore.setItem("nlp1.family_graph_id", "남아있던 익명 값");

    clearAllScopedKeys();

    expect(readScoped(SESSION_ID_KEY)).toBeNull();
    expect(readScoped("nlp1.family_graph_id")).toBeNull();
  });

  it("clearScoped 는 지정한 키만 양쪽에서 지운다", () => {
    writeScoped(SESSION_ID_KEY, "s-1");
    writeScoped("nlp1.family_graph_id", "g-1");

    clearScoped(SESSION_ID_KEY);

    expect(readScoped(SESSION_ID_KEY)).toBeNull();
    expect(readScoped("nlp1.family_graph_id")).toBe("g-1");
  });
});

describe("저장소 접근이 막힌 환경", () => {
  it("throw 하는 저장소에서도 앱이 죽지 않는다", () => {
    const exploding = {
      get localStorage(): Storage {
        throw new Error("접근 거부 (프라이빗 브라우징)");
      },
      get sessionStorage(): Storage {
        throw new Error("접근 거부 (프라이빗 브라우징)");
      },
    };
    (globalThis as { window?: unknown }).window = exploding;

    expect(() => writeScoped(SESSION_ID_KEY, "s-1")).not.toThrow();
    expect(readScoped(SESSION_ID_KEY)).toBeNull();
    expect(() => clearAllScopedKeys()).not.toThrow();
  });
});
