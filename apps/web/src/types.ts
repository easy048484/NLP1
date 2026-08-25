/**
 * 백엔드 apps/api/schemas/agent_io.py 의 AgentInput / AgentOutput 계약과
 * 1:1로 맞춘 프론트엔드 타입입니다. 백엔드 스키마가 바뀌면 여기도 같이
 * 바꿔주세요 — 이 타입들이 개발자 모드의 요청/응답 JSON 뷰어와
 * 실제 fetch 호출 양쪽에서 공통으로 쓰입니다.
 */

export type AgentName = "heir_navigator" | "decedent_estate" | "tax_calculator";

export interface AgentInput {
  session_id: string;
  user_message: string;
  family_graph?: Record<string, unknown> | null;
  family_graph_id?: string | null;
  context: Record<string, unknown>;
}

export interface AgentOutput {
  agent: AgentName;
  reply: string;
  next_action?: string | null;
  data: Record<string, unknown>;
}

/**
 * apps/api/family_graph/schemas.py의 트리 저장/조회 계약과 1:1로 맞춘
 * 타입입니다. persons의 key는 요청 안에서만 유효한 임시 식별자로,
 * relations가 참조하며 서버에 저장되지는 않습니다.
 */

export type RelationEdgeType = "parent_of" | "spouse_of";

export interface PersonIn {
  key: string;
  name: string;
  is_decedent?: boolean;
  is_alive?: boolean;
  is_minor?: boolean;
}

export interface RelationIn {
  type: RelationEdgeType;
  from_key: string;
  to_key: string;
}

export interface FamilyTreeIn {
  persons: PersonIn[];
  relations: RelationIn[];
}

export interface PersonOut {
  id: number;
  name: string;
  is_decedent: boolean;
  is_alive: boolean;
  is_minor: boolean;
}

export interface RelationOut {
  id: number;
  type: RelationEdgeType;
  from_person_id: number;
  to_person_id: number;
}

export interface FamilyTreeOut {
  id: string;
  created_at: string;
  persons: PersonOut[];
  relations: RelationOut[];
}
