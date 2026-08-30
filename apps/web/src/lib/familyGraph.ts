import type {
  FamilyGraphOut,
  FamilyMemberIn,
  FamilyMemberOut,
  FamilyMemberPatch,
} from "../types";
import { API_BASE_URL } from "./api";
import { authHeader } from "./auth";
import {
  clearFamilyGraphId,
  getFamilyGraphId,
  setFamilyGraphId as persistFamilyGraphId,
} from "./familyGraphStorage";

/**
 * apps/api/family_graph/router.py 의 REST API를 호출하는 클라이언트입니다.
 * lib/api.ts의 sendChatMessage와 같은 결과 형태(ok/status/errorMessage)를
 * 따라서 호출부(FamilyIntake, FamilyGraphPanel)가 일관되게 에러를 처리할
 * 수 있게 했습니다.
 */
export interface FamilyGraphCallResult<T> {
  ok: boolean;
  status: number | null;
  data: T | null;
  errorMessage: string | null;
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<FamilyGraphCallResult<T>> {
  try {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...authHeader(), ...init?.headers },
    });

    let json: unknown = null;
    if (res.status !== 204) {
      try {
        json = await res.json();
      } catch {
        json = null;
      }
    }

    if (!res.ok) {
      const detail =
        json !== null && typeof json === "object" && "detail" in json
          ? JSON.stringify((json as { detail: unknown }).detail)
          : `HTTP ${res.status}`;
      return { ok: false, status: res.status, data: null, errorMessage: detail };
    }

    return { ok: true, status: res.status, data: json as T, errorMessage: null };
  } catch (err) {
    return {
      ok: false,
      status: null,
      data: null,
      errorMessage:
        err instanceof Error
          ? err.message
          : "알 수 없는 오류로 서버에 연결하지 못했습니다.",
    };
  }
}

/** POST /family-graph — 새 가족관계 그래프를 만듭니다. */
export function createFamilyGraph(): Promise<FamilyGraphCallResult<FamilyGraphOut>> {
  return request<FamilyGraphOut>("/family-graph", { method: "POST" });
}

/**
 * 지금 쓸 수 있는 가족관계 그래프를 확보합니다.
 * - localStorage 에 id 가 있고 서버에도 아직 있으면 그 그래프를 그대로 반환.
 * - id 가 없거나, 서버에서 사라졌으면(배포 시 DB 재생성·만료 배치 등 → 404)
 *   저장된 id 를 지우고 새로 만들어 반환. 새 id 는 localStorage 에 반영됨.
 *
 * "family_graph를 찾을 수 없습니다" 404 로 인테이크가 막히던 문제의 근본 해결.
 */
export async function ensureFamilyGraph(): Promise<
  FamilyGraphCallResult<FamilyGraphOut>
> {
  const stored = getFamilyGraphId();
  if (stored) {
    const existing = await getFamilyGraph(stored);
    if (existing.ok && existing.data) return existing;
    // 404 = 서버에서 사라진 id → 지우고 새로 만든다.
    // 그 외(503·네트워크 등 일시적 오류)는 id 를 지우지 않고 그 오류를 그대로 올린다.
    if (existing.status !== 404) return existing;
    clearFamilyGraphId();
  }
  const created = await createFamilyGraph();
  if (created.ok && created.data) persistFamilyGraphId(created.data.id);
  return created;
}

/** GET /family-graph/{id} — 현재 구성원 목록을 조회합니다. */
export function getFamilyGraph(
  familyGraphId: string,
): Promise<FamilyGraphCallResult<FamilyGraphOut>> {
  return request<FamilyGraphOut>(`/family-graph/${familyGraphId}`, {
    method: "GET",
  });
}

/**
 * GET /family-graph/mine — 로그인한 사용자가 소유한 가족관계 그래프.
 * 없으면 status 404 (ok: false)로 돌아옵니다.
 */
export function getMyFamilyGraph(): Promise<
  FamilyGraphCallResult<FamilyGraphOut>
> {
  return request<FamilyGraphOut>("/family-graph/mine", { method: "GET" });
}

/**
 * POST /family-graph/{id}/claim — 로그인 전 익명으로 만든 그래프를 지금
 * 로그인한 계정에 연결합니다. 이미 내 것이면 그대로, 남의 것이면 404.
 */
export function claimFamilyGraph(
  familyGraphId: string,
): Promise<FamilyGraphCallResult<FamilyGraphOut>> {
  return request<FamilyGraphOut>(`/family-graph/${familyGraphId}/claim`, {
    method: "POST",
  });
}

/** POST /family-graph/{id}/members — 구성원 한 명을 추가합니다. */
export function addFamilyMember(
  familyGraphId: string,
  member: FamilyMemberIn,
): Promise<FamilyGraphCallResult<FamilyMemberOut>> {
  return request<FamilyMemberOut>(`/family-graph/${familyGraphId}/members`, {
    method: "POST",
    body: JSON.stringify(member),
  });
}

/**
 * PATCH /family-graph/{id}/members/{member_id} — 구성원 정보를 부분
 * 수정합니다. patch에 넣은 필드만 바뀝니다.
 */
export function updateFamilyMember(
  familyGraphId: string,
  memberId: number,
  patch: FamilyMemberPatch,
): Promise<FamilyGraphCallResult<FamilyMemberOut>> {
  return request<FamilyMemberOut>(
    `/family-graph/${familyGraphId}/members/${memberId}`,
    { method: "PATCH", body: JSON.stringify(patch) },
  );
}

/** DELETE /family-graph/{id}/members/{member_id} — 구성원 한 명을 삭제합니다. */
export function deleteFamilyMember(
  familyGraphId: string,
  memberId: number,
): Promise<FamilyGraphCallResult<null>> {
  return request<null>(`/family-graph/${familyGraphId}/members/${memberId}`, {
    method: "DELETE",
  });
}
